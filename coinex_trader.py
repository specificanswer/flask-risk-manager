import ccxt
import time
import threading
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Union, Optional
import argparse


class CryptoFuturesTrader:
    def __init__(
        self,
        exchange_id: str,
        api_key: str,
        secret_key: str,
        config_path: str = "trader_config.json",
    ):
        # Risk parameters
        self.max_trades_per_day = 25
        self.cooldown_minutes = 1
        self.max_daily_loss = 20.0  # USD
        self.max_position_size = 5.0  # USD

        # State tracking
        self.daily_trade_count = 0
        self.daily_pnl = 0.0
        self.last_trade_time = None
        self.trades_history = []
        self.config_path = config_path
        self.exchange_id = exchange_id.lower()

        # Initialize exchange connection
        self.exchange = self._initialize_exchange(exchange_id, api_key, secret_key)

        # Load state if exists
        self._load_state()

        # Monitoring system
        self.monitoring_active = False
        self.monitor_thread = None
        self.pending_monitors = {}  # Store SL/TP targets for positions
        self.check_interval = 5  # Check positions every 5 seconds

    def check_limit_order_status(self, order_id=None):
        """
        Check the status of limit orders and update their status if filled.
        If order_id is provided, only check that specific order.
        """
        try:
            # Find pending limit orders to check
            pending_orders = []

            if order_id:
                # Check specific order
                for trade in self.trades_history:
                    if (
                        trade.get("order_id") == order_id
                        and trade.get("status") == "pending"
                    ):
                        pending_orders.append(trade)
            else:
                # Check all pending orders
                for trade in self.trades_history:
                    if (
                        trade.get("status") == "pending"
                        and trade.get("order_type") == "limit"
                    ):
                        pending_orders.append(trade)

            if not pending_orders:
                return {"success": True, "message": "No pending orders to check"}

            print(f"Checking status of {len(pending_orders)} pending limit orders")

            # Check each pending order
            updated_orders = []

            for trade in pending_orders:
                order_id = trade.get("order_id")
                if not order_id or order_id == "unknown":
                    continue

                try:
                    # Fetch the order status from the exchange
                    order = self.exchange.fetch_order(order_id, trade.get("symbol"))
                    print(f"Order {order_id} status: {order.get('status')}")

                    # Update the order status
                    if (
                        order.get("status") == "closed"
                        or order.get("status") == "filled"
                    ):
                        trade["status"] = "filled"
                        self.daily_trade_count += 1
                        self.last_trade_time = datetime.now()
                        updated_orders.append(
                            {"order_id": order_id, "status": "filled"}
                        )
                        print(
                            f"Limit order {order_id} is now filled - counted as trade #{self.daily_trade_count}"
                        )
                    elif (
                        order.get("status") == "canceled"
                        or order.get("status") == "cancelled"
                    ):
                        trade["status"] = "canceled"
                        updated_orders.append(
                            {"order_id": order_id, "status": "canceled"}
                        )
                        print(
                            f"Limit order {order_id} was canceled - not counted as trade"
                        )
                except Exception as e:
                    print(f"Error checking order {order_id}: {e}")

            # Save state if any orders were updated
            if updated_orders:
                self._save_state()
                return {
                    "success": True,
                    "message": f"Updated {len(updated_orders)} orders",
                    "updated": updated_orders,
                }
            else:
                return {"success": True, "message": "No orders needed updating"}

        except Exception as e:
            print(f"Error checking limit orders: {e}")
            return {
                "success": False,
                "message": f"Error checking limit orders: {str(e)}",
            }

    def update_order_status(self, order_id, new_status):
        """Update the status of an order and handle filled orders."""
        updated = False

        for trade in self.trades_history:
            if trade.get("order_id") == order_id:
                old_status = trade.get("status")
                trade["status"] = new_status
                updated = True

                # If this is a limit order being marked as filled
                if old_status == "pending" and new_status == "filled":
                    self.last_trade_time = datetime.now()
                    self.daily_trade_count += 1
                    print(
                        f"Limit order {order_id} marked as filled - counted as trade #{self.daily_trade_count}"
                    )

                # If this is an order being marked as canceled
                elif new_status == "canceled":
                    print(
                        f"Order {order_id} marked as canceled - not counted as a trade"
                    )

                self._save_state()
                break

        return {
            "success": updated,
            "message": (
                f"Order {order_id} status updated to {new_status}"
                if updated
                else f"Order {order_id} not found"
            ),
        }

    def start_monitoring(self):
        """Start the position monitoring system"""
        if not self.monitoring_active:
            self.monitoring_active = True
            self.monitor_thread = threading.Thread(target=self._monitor_positions)
            self.monitor_thread.daemon = (
                True  # Thread will stop when main program stops
            )
            self.monitor_thread.start()
            print("Position monitoring system started")

    def stop_monitoring(self):
        """Stop the position monitoring system"""
        self.monitoring_active = False
        if self.monitor_thread:
            self.monitor_thread.join()
        print("Position monitoring system stopped")

    def _monitor_positions(self):
        """Background thread that monitors positions for SL/TP"""
        while self.monitoring_active:
            try:
                positions = self.get_open_positions()
                print(f"\n=== Monitoring {len(positions)} positions ===")

                for position in positions:
                    symbol = position.get("symbol")

                    # Get PnL for stop loss check
                    pnl = float(position.get("unrealizedPnl") or 0)
                    side = position.get("side")

                    print(f"\nChecking {symbol}: PnL=${pnl:.2f}, Side={side}")

                    # Check if we have monitoring targets
                    monitor = None
                    monitor_key = None

                    # Find matching monitor
                    for key, data in self.pending_monitors.items():
                        if key == symbol or key in symbol or symbol in key:
                            monitor = data
                            monitor_key = key
                            break

                    if monitor:
                        stop_loss = monitor.get("stop_loss")
                        take_profit = monitor.get("take_profit")

                        print(f"Monitor found: SL={stop_loss}, TP={take_profit}")

                        # Check both PnL-based stop loss AND price-based stop loss
                        trigger_close = False
                        close_reason = ""

                        # Check PnL-based stop loss ($5 max loss)
                        if pnl <= -5.0:
                            trigger_close = True
                            close_reason = f"PnL Stop Loss: ${pnl:.2f}"

                        # Check price-based stop loss if specified
                        elif stop_loss:
                            try:
                                ticker = self.exchange.fetch_ticker(symbol)
                                current_price = float(ticker.get("last", 0))

                                print(
                                    f"Checking price-based SL: Current price={current_price}, SL={stop_loss}"
                                )

                                # For long positions: close if price <= stop loss
                                if side == "long" and current_price <= stop_loss:
                                    trigger_close = True
                                    close_reason = f"Price Stop Loss: {current_price} <= {stop_loss}"

                                # For short positions: close if price >= stop loss
                                elif side == "short" and current_price >= stop_loss:
                                    trigger_close = True
                                    close_reason = f"Price Stop Loss: {current_price} >= {stop_loss}"

                            except Exception as e:
                                print(f"Error checking price-based stop loss: {e}")

                        # Execute close if triggered
                        if trigger_close:
                            print(f">>> STOP LOSS TRIGGERED: {close_reason}")
                            print(f"Attempting to close position {symbol}")
                            result = self.close_position(symbol)
                            print(f"Close result: {result}")

                            if result.get("success"):
                                self.pending_monitors.pop(monitor_key, None)
                                print(f"Position closed - Stop loss")
                            else:
                                print(
                                    f"Failed to close position: {result.get('message', 'Unknown error')}"
                                )
                            continue

                        # Check take profit
                        if take_profit:
                            try:
                                ticker = self.exchange.fetch_ticker(symbol)
                                current_price = float(ticker.get("last", 0))

                                print(
                                    f"Current price from ticker: {current_price}, TP target: {take_profit}"
                                )

                                # Check take profit conditions
                                if side == "long" and current_price >= take_profit:
                                    print(
                                        f">>> TAKE PROFIT TRIGGERED: Price {current_price} >= {take_profit}"
                                    )
                                    print(f"Attempting to close position {symbol}")
                                    result = self.close_position(symbol)
                                    print(f"Close result: {result}")

                                    if result.get("success"):
                                        self.pending_monitors.pop(monitor_key, None)
                                        print(f"Position closed - Take profit")
                                    else:
                                        print(
                                            f"Failed to close position: {result.get('message', 'Unknown error')}"
                                        )

                                elif side == "short" and current_price <= take_profit:
                                    print(
                                        f">>> TAKE PROFIT TRIGGERED: Price {current_price} <= {take_profit}"
                                    )
                                    print(f"Attempting to close position {symbol}")
                                    result = self.close_position(symbol)
                                    print(f"Close result: {result}")

                                    if result.get("success"):
                                        self.pending_monitors.pop(monitor_key, None)
                                        print(f"Position closed - Take profit")
                                    else:
                                        print(
                                            f"Failed to close position: {result.get('message', 'Unknown error')}"
                                        )

                            except Exception as e:
                                print(f"Error fetching ticker price: {e}")
                                import traceback

                                traceback.print_exc()

                print(f"\n=== Monitoring cycle complete ===")
                time.sleep(self.check_interval)

            except Exception as e:
                print(f"Monitor error: {e}")
                import traceback

                traceback.print_exc()
                time.sleep(self.check_interval)

    def normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol format for comparison"""
        # Remove common variations
        normalized = (
            symbol.replace(":USDT", "").replace("/USDT", "").replace("USDT", "")
        )
        # Add back /USDT format
        if "/" not in normalized:
            normalized = normalized + "/USDT"
        return normalized

    def debug_monitors(self):
        """Debug method to see current monitoring status"""
        print("=== MONITORING DEBUG ===")
        print(f"Monitoring active: {self.monitoring_active}")
        print(f"Pending monitors: {self.pending_monitors}")

        positions = self.get_open_positions()
        for position in positions:
            symbol = position.get("symbol")
            print(f"\nPosition {symbol}:")
            print(f"  Full position data: {position}")

        return self.pending_monitors

    def get_monitoring_status(self):
        """Get current monitoring status"""
        return {
            "active": self.monitoring_active,
            "monitored_positions": list(self.pending_monitors.keys()),
            "check_interval": self.check_interval,
        }

    def _initialize_exchange(self, exchange_id: str, api_key: str, secret_key: str):
        """Initialize connection to the exchange."""
        try:
            exchange_class = getattr(ccxt, exchange_id)

            # Special configuration for CoinEx
            if exchange_id.lower() == "coinex":
                exchange = exchange_class(
                    {
                        "apiKey": api_key,
                        "secret": secret_key,
                        "enableRateLimit": True,
                        "options": {
                            "defaultType": "swap",  # CoinEx uses 'swap' for futures
                            "createMarketBuyOrderRequiresPrice": False,
                        },
                    }
                )
            else:
                exchange = exchange_class(
                    {
                        "apiKey": api_key,
                        "secret": secret_key,
                        "enableRateLimit": True,
                        "options": {"defaultType": "future"},
                    }
                )

            # Load markets
            exchange.load_markets()

            print(f"Successfully connected to {exchange_id}")
            return exchange
        except Exception as e:
            print(f"Error connecting to exchange: {e}")
            raise

    def _load_state(self):
        """Load trading state from file if it exists."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    state = json.load(f)

                # Check if state is from today
                last_date = datetime.fromisoformat(state.get("date", "2000-01-01"))
                if last_date.date() == datetime.now().date():
                    self.daily_trade_count = state.get("daily_trade_count", 0)
                    self.daily_pnl = state.get("daily_pnl", 0.0)
                    self.last_trade_time = (
                        datetime.fromisoformat(state.get("last_trade_time"))
                        if state.get("last_trade_time")
                        else None
                    )
                    self.trades_history = state.get("trades_history", [])
                    print(
                        f"Loaded today's state: {self.daily_trade_count} trades, ${self.daily_pnl} PnL"
                    )
                else:
                    print("New trading day, resetting state")
            except Exception as e:
                print(f"Error loading state: {e}")

    def _save_state(self):
        """Save current trading state to file."""
        state = {
            "date": datetime.now().isoformat(),
            "daily_trade_count": self.daily_trade_count,
            "daily_pnl": self.daily_pnl,
            "last_trade_time": (
                self.last_trade_time.isoformat() if self.last_trade_time else None
            ),
            "trades_history": self.trades_history,
        }

        with open(self.config_path, "w") as f:
            json.dump(state, f, indent=4)

    def can_trade(self) -> Dict[str, Union[bool, str]]:
        """Check if trading is allowed based on risk rules."""
        now = datetime.now()

        # Check if we're in a new day and reset counters if needed
        if self.last_trade_time and self.last_trade_time.date() < now.date():
            self.daily_trade_count = 0
            self.daily_pnl = 0.0
            self.trades_history = []
            print("New day detected, reset daily counters")

        # Check max trades per day
        if self.daily_trade_count >= self.max_trades_per_day:
            return {
                "allowed": False,
                "reason": f"Max daily trades ({self.max_trades_per_day}) reached",
            }

        # Check cooldown period
        if self.last_trade_time and now < self.last_trade_time + timedelta(
            minutes=self.cooldown_minutes
        ):
            cooldown_ends = self.last_trade_time + timedelta(
                minutes=self.cooldown_minutes
            )
            wait_mins = (cooldown_ends - now).total_seconds() / 60
            return {
                "allowed": False,
                "reason": f"Cooldown period active. Wait {wait_mins:.1f} more minutes",
            }

        # Check daily loss limit
        if self.daily_pnl <= -self.max_daily_loss:
            return {
                "allowed": False,
                "reason": f"Daily loss limit (${self.max_daily_loss}) reached",
            }

        return {"allowed": True, "reason": "Trading allowed"}

    def format_symbol_for_exchange(self, symbol: str) -> str:
        """Format symbol according to exchange requirements."""
        # CoinEx uses specific symbol formats for futures/swaps
        if self.exchange_id == "coinex":
            # CoinEx swap markets are typically in the format BTCUSDT or similar without '/'
            if "/" in symbol:
                # Convert BTC/USDT to BTCUSDT format
                formatted_symbol = symbol.replace("/", "")

                # Check if this market exists
                markets = self.exchange.markets
                for market_id in markets:
                    if market_id.upper() == formatted_symbol.upper():
                        return market_id  # Return the exact case as in the exchange

                # If no exact match, return the transformed format
                return formatted_symbol

        # For other exchanges or if no special formatting is needed, return as is
        return symbol

    def check_order_types(self, symbol: str):
        """Check available order types for a symbol."""
        try:
            formatted_symbol = self.format_symbol_for_exchange(symbol)

            # Try to get market info
            market = self.exchange.market(formatted_symbol)
            print(f"Market info for {formatted_symbol}:")
            print(f"Market type: {market.get('type')}")
            print(f"Market info: {market.get('info', {})}")

            # Try to fetch order types using exchange capabilities
            if hasattr(self.exchange, "has"):
                print(f"Exchange capabilities: {self.exchange.has}")

            return True
        except Exception as e:
            print(f"Error checking order types: {e}")
            return False

    def place_trade(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float = None,
        stop_loss: float = None,
        take_profit: float = None,
        leverage: int = 5,
        margin_mode: str = "isolated",
        post_only: bool = False,
    ) -> Dict:
        """
        Place a trade with risk management and advanced order features.
        """
        # Debug output
        print(
            f"Trade request: Symbol={symbol}, Side={side}, Amount={amount}, Price={price}, Type={'market' if price is None else 'limit'}"
        )

        # Check risk parameters
        trade_check = self.can_trade()
        if not trade_check["allowed"]:
            print(f"Trade rejected: {trade_check['reason']}")
            return {"success": False, "message": trade_check["reason"]}

        # Check position size
        if amount > self.max_position_size:
            return {
                "success": False,
                "message": f"Position size (${amount}) exceeds maximum (${self.max_position_size})",
            }

        try:
            # Make sure markets are loaded
            if not self.exchange.markets:
                self.exchange.load_markets()

            # Format symbol for the specific exchange
            formatted_symbol = self.format_symbol_for_exchange(symbol)

            # Get market info for proper sizing
            try:
                market = self.exchange.market(formatted_symbol)
            except Exception as e:
                return {
                    "success": False,
                    "message": f"Symbol not found or not supported: {formatted_symbol}. Error: {str(e)}",
                }

            # Set leverage first
            try:
                self.exchange.set_leverage(leverage, formatted_symbol)
                print(f"Set leverage to {leverage}x for {formatted_symbol}")
            except Exception as e:
                print(f"Warning: Could not set leverage - {str(e)}")

            # Set margin mode
            try:
                if self.exchange_id == "coinex":
                    # CoinEx requires leverage parameter with margin mode
                    self.exchange.set_margin_mode(
                        margin_mode, formatted_symbol, {"leverage": leverage}
                    )
                else:
                    self.exchange.set_margin_mode(margin_mode, formatted_symbol)
                print(f"Set margin mode to {margin_mode} for {formatted_symbol}")
            except Exception as e:
                print(f"Warning: Could not set margin mode - {str(e)}")

            # Calculate quantity based on current price if not specified
            if not price:
                try:
                    ticker = self.exchange.fetch_ticker(formatted_symbol)
                    price_for_calculation = ticker["last"]
                    print(f"Got market price for calculation: {price_for_calculation}")
                except Exception as e:
                    return {
                        "success": False,
                        "message": f"Could not fetch price for {formatted_symbol}. Error: {str(e)}",
                    }
            else:
                price_for_calculation = price

            # Convert USD amount to actual quantity
            quantity = amount / price_for_calculation
            print(
                f"Calculated quantity: {quantity} (${amount} / {price_for_calculation})"
            )

            # Adjust for minimum quantity requirements
            if "limits" in market and "amount" in market["limits"]:
                min_amount = market["limits"]["amount"]["min"]
                if quantity < min_amount:
                    quantity = min_amount
                    print(f"Adjusted quantity to minimum: {quantity}")

            # Determine order type
            order_type = "market" if price is None else "limit"
            print(f"Order type: {order_type}")

            # Exchange-specific order parameters
            if self.exchange_id == "coinex":
                # For CoinEx swap
                order_params = {
                    "leverage": leverage,
                }

                # Add post-only parameter if requested
                if post_only and order_type == "limit":
                    order_params["timeInForce"] = "PO"  # Post Only
            else:
                order_params = {"type": "future"}
                if post_only and order_type == "limit":
                    order_params["postOnly"] = True

            print(
                f"Placing {order_type} order: {side} {quantity} {formatted_symbol} @ {price if price else 'market'}"
            )

            # Place the actual order
            if order_type == "limit":
                order = self.exchange.create_order(
                    formatted_symbol, "limit", side, quantity, price, order_params
                )
            else:
                order = self.exchange.create_order(
                    formatted_symbol, "market", side, quantity, None, order_params
                )

            print(f"Order placed: {order}")

            # After successfully placing the main order...
            order_id = order.get("id", "unknown")

            # Determine if this is a market or limit order
            is_market_order = order_type == "market"

            # Record trade
            trade_record = {
                "time": datetime.now().isoformat(),
                "symbol": formatted_symbol,
                "side": side,
                "amount": amount,
                "price": price_for_calculation if is_market_order else price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "leverage": leverage,
                "margin_mode": margin_mode,
                "post_only": post_only,
                "order_id": order_id,
                "order_type": order_type,
                "status": "filled" if is_market_order else "pending",
            }

            # Increment trade count for market orders
            if is_market_order:
                self.last_trade_time = datetime.now()
                self.daily_trade_count += 1
                print(f"Market order counted as trade #{self.daily_trade_count}")

            # Add SL/TP to monitoring
            if stop_loss or take_profit:
                # Use the actual symbol format returned by the exchange
                actual_symbol = order.get("symbol", formatted_symbol)

                self.pending_monitors[actual_symbol] = {
                    "side": side,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "entry_price": price if price else price_for_calculation,
                    "quantity": quantity,
                }

                print(f"Added monitor for symbol: {actual_symbol}")

            # Add to trade history
            self.trades_history.append(trade_record)

            # Save state
            self._save_state()

            return {
                "success": True,
                "order": order,
                "message": f"Successfully placed {side} {order_type} order for {formatted_symbol}",
            }

        except Exception as e:
            error_msg = str(e)
            print(f"Error placing trade: {error_msg}")
            # Check for common exchange-specific errors
            if "balance" in error_msg.lower():
                return {
                    "success": False,
                    "message": f"Insufficient balance. Error: {error_msg}",
                }
            elif "permission" in error_msg.lower():
                return {
                    "success": False,
                    "message": f"API permission issue. Make sure your API key has trading permissions. Error: {error_msg}",
                }
            elif "symbol" in error_msg.lower():
                return {
                    "success": False,
                    "message": f"Symbol error. The pair {symbol} may not be available for futures trading. Error: {error_msg}",
                }
            else:
                return {
                    "success": False,
                    "message": f"Error placing trade: {self.exchange_id} {error_msg}",
                }

    def update_pnl(self, trade_pnl: float):
        """
        Update the daily PnL after a trade is closed.

        Args:
            trade_pnl: Profit/loss from the closed trade in USD
        """
        self.daily_pnl += trade_pnl
        print(f"Updated daily PnL: ${self.daily_pnl:.2f}")

        # Check if we've hit daily loss limit
        if self.daily_pnl <= -self.max_daily_loss:
            print(
                f"WARNING: Daily loss limit of ${self.max_daily_loss} has been reached. Trading stopped for today."
            )

        self._save_state()

    def get_trading_status(self) -> Dict:
        """Get current trading status and risk metrics."""
        can_trade_result = self.can_trade()

        # If self.daily_trade_count is incorrect, recount from trade history
        filled_trades_today = []
        today = datetime.now().date()

        for trade in self.trades_history:
            if trade.get("status") == "filled":
                try:
                    trade_time = datetime.fromisoformat(trade.get("time"))
                    if trade_time.date() == today:
                        filled_trades_today.append(trade)
                except:
                    # Skip trades with invalid time format
                    pass

        # Reset daily trade count if it doesn't match filled trades
        if len(filled_trades_today) != self.daily_trade_count:
            print(
                f"WARNING: Trade count mismatch. Resetting from {self.daily_trade_count} to {len(filled_trades_today)}"
            )
            self.daily_trade_count = len(filled_trades_today)
            self._save_state()

        return {
            "exchange": self.exchange_id,
            "date": datetime.now().isoformat(),
            "can_trade": can_trade_result["allowed"],
            "status_message": can_trade_result["reason"],
            "daily_trade_count": self.daily_trade_count,
            "max_trades_per_day": self.max_trades_per_day,
            "trades_remaining": max(
                0, self.max_trades_per_day - self.daily_trade_count
            ),
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_loss_limit": self.max_daily_loss,
            "max_position_size": self.max_position_size,
            "last_trade_time": (
                self.last_trade_time.isoformat() if self.last_trade_time else None
            ),
            "cooldown_ends": (
                (
                    self.last_trade_time + timedelta(minutes=self.cooldown_minutes)
                ).isoformat()
                if self.last_trade_time
                else None
            ),
            "trades_history": self.trades_history,
        }

    def get_open_positions(self) -> List[Dict]:
        """Get all open futures positions."""
        try:
            if self.exchange_id == "coinex":
                # CoinEx might require specific method or endpoint
                positions = self.exchange.fetch_positions()
                return [p for p in positions if float(p.get("contracts", 0)) > 0]
            else:
                positions = self.exchange.fetch_positions()
                return [p for p in positions if float(p.get("contracts", 0)) > 0]
        except Exception as e:
            print(f"Error fetching positions: {e}")
            return []

    def close_position(
        self, symbol: str, order_type: str = "market", limit_price: float = None
    ) -> Dict:
        """Close an open position for a symbol."""
        try:
            positions = self.get_open_positions()

            # Find the position with matching symbol (handle format variations)
            position = None
            actual_symbol = None

            for p in positions:
                pos_symbol = p.get("symbol")
                if pos_symbol == symbol or symbol in pos_symbol or pos_symbol in symbol:
                    position = p
                    actual_symbol = pos_symbol
                    break

            if not position:
                return {
                    "success": False,
                    "message": f"No open position found for {symbol}",
                }

            print(f"Closing position with actual symbol: {actual_symbol}")
            print(f"Order type: {order_type}, Limit price: {limit_price}")

            # Determine close direction (opposite of position)
            side = "sell" if position["side"] == "long" else "buy"
            amount = abs(float(position["contracts"]))

            # Place closing order with exchange-specific parameters
            if self.exchange_id == "coinex":
                if order_type == "limit" and limit_price:
                    order = self.exchange.create_order(
                        actual_symbol,
                        "limit",
                        side,
                        amount,
                        limit_price,
                        {"reduceOnly": True},
                    )
                else:
                    # Default to market order
                    order = self.exchange.create_order(
                        actual_symbol,
                        "market",
                        side,
                        amount,
                        None,
                        {"reduceOnly": True},
                    )
            else:
                if order_type == "limit" and limit_price:
                    order = self.exchange.create_order(
                        actual_symbol,
                        "limit",
                        side,
                        amount,
                        limit_price,
                        {"reduceOnly": True, "type": "future"},
                    )
                else:
                    order = self.exchange.create_order(
                        actual_symbol,
                        "market",
                        side,
                        amount,
                        None,
                        {"reduceOnly": True, "type": "future"},
                    )

            return {
                "success": True,
                "order": order,
                "message": f"Successfully closed position for {actual_symbol} with {order_type} order",
            }

        except Exception as e:
            return {"success": False, "message": f"Error closing position: {str(e)}"}

    def update_risk_parameters(
        self,
        max_trades=None,
        cooldown_mins=None,
        max_daily_loss=None,
        max_position_size=None,
    ):
        """Update risk management parameters."""
        if max_trades is not None:
            self.max_trades_per_day = max_trades
        if cooldown_mins is not None:
            self.cooldown_minutes = cooldown_mins
        if max_daily_loss is not None:
            self.max_daily_loss = max_daily_loss
        if max_position_size is not None:
            self.max_position_size = max_position_size

        print(f"Updated risk parameters: {self.get_risk_parameters()}")
        self._save_state()

    def get_risk_parameters(self):
        """Get current risk management parameters."""
        return {
            "max_trades_per_day": self.max_trades_per_day,
            "cooldown_minutes": self.cooldown_minutes,
            "max_daily_loss": self.max_daily_loss,
            "max_position_size": self.max_position_size,
        }


def main():
    parser = argparse.ArgumentParser(
        description="Crypto Futures Trader with Risk Management"
    )
    parser.add_argument(
        "--exchange",
        type=str,
        required=True,
        help="Exchange ID (e.g., coinex, binance)",
    )
    parser.add_argument(
        "--config", type=str, default="trader_config.json", help="Path to config file"
    )
    parser.add_argument("--apikey", type=str, required=True, help="API Key")
    parser.add_argument("--secret", type=str, required=True, help="Secret Key")

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Status command
    status_parser = subparsers.add_parser("status", help="Get trading status")

    # Trade command
    trade_parser = subparsers.add_parser("trade", help="Place a trade")
    trade_parser.add_argument(
        "--symbol", type=str, required=True, help="Trading pair (e.g., BTC/USDT)"
    )
    trade_parser.add_argument(
        "--side",
        type=str,
        required=True,
        choices=["buy", "sell"],
        help="Trade direction",
    )
    trade_parser.add_argument(
        "--amount", type=float, required=True, help="Position size in USD"
    )
    trade_parser.add_argument(
        "--price",
        type=float,
        help="Limit price (optional, market order if not specified)",
    )
    trade_parser.add_argument("--stop-loss", type=float, help="Stop loss price")
    trade_parser.add_argument("--take-profit", type=float, help="Take profit price")
    trade_parser.add_argument(
        "--leverage", type=int, default=5, help="Leverage multiplier"
    )
    trade_parser.add_argument(
        "--margin-mode",
        type=str,
        default="isolated",
        choices=["isolated", "cross"],
        help="Margin mode",
    )
    trade_parser.add_argument(
        "--post-only",
        action="store_true",
        help="Make order post-only (limit orders only)",
    )

    # Close position command
    close_parser = subparsers.add_parser("close", help="Close an open position")
    close_parser.add_argument(
        "--symbol", type=str, required=True, help="Trading pair to close"
    )

    # Update PnL command
    pnl_parser = subparsers.add_parser("pnl", help="Update daily PnL")
    pnl_parser.add_argument(
        "--amount", type=float, required=True, help="Profit/loss amount in USD"
    )

    # Positions command
    positions_parser = subparsers.add_parser("positions", help="Get open positions")

    # Update risk parameters command
    risk_parser = subparsers.add_parser("risk", help="Update risk parameters")
    risk_parser.add_argument("--max-trades", type=int, help="Maximum trades per day")
    risk_parser.add_argument("--cooldown", type=int, help="Cooldown period in minutes")
    risk_parser.add_argument("--max-loss", type=float, help="Maximum daily loss in USD")
    risk_parser.add_argument(
        "--max-size", type=float, help="Maximum position size in USD"
    )

    args = parser.parse_args()

    # Initialize trader
    trader = CryptoFuturesTrader(args.exchange, args.apikey, args.secret, args.config)

    # Execute command
    if args.command == "status":
        status = trader.get_trading_status()
        print(json.dumps(status, indent=2))

    elif args.command == "trade":
        result = trader.place_trade(
            args.symbol,
            args.side,
            args.amount,
            args.price,
            args.stop_loss,
            args.take_profit,
            args.leverage,
            args.margin_mode,
            args.post_only,
        )
        print(json.dumps(result, indent=2))

    elif args.command == "close":
        result = trader.close_position(args.symbol)
        print(json.dumps(result, indent=2))

    elif args.command == "pnl":
        trader.update_pnl(args.amount)
        status = trader.get_trading_status()
        print(json.dumps(status, indent=2))

    elif args.command == "positions":
        positions = trader.get_open_positions()
        print(json.dumps(positions, indent=2))

    elif args.command == "risk":
        trader.update_risk_parameters(
            args.max_trades, args.cooldown, args.max_loss, args.max_size
        )
        print(json.dumps(trader.get_risk_parameters(), indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
