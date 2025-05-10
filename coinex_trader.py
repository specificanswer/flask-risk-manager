import ccxt
import time
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Union, Optional
import argparse

class CryptoFuturesTrader:
    def __init__(self, exchange_id: str, api_key: str, secret_key: str, config_path: str = "trader_config.json"):
        # Risk parameters
        self.max_trades_per_day = 5
        self.cooldown_minutes = 10
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
    
    def _initialize_exchange(self, exchange_id: str, api_key: str, secret_key: str):
        """Initialize connection to the exchange."""
        try:
            exchange_class = getattr(ccxt, exchange_id)
            
            # Special configuration for CoinEx
            if exchange_id.lower() == 'coinex':
                exchange = exchange_class({
                    'apiKey': api_key,
                    'secret': secret_key,
                    'enableRateLimit': True,
                    'options': {
                        'defaultType': 'swap',  # CoinEx uses 'swap' for futures
                        'createMarketBuyOrderRequiresPrice': False,
                    }
                })
            else:
                exchange = exchange_class({
                    'apiKey': api_key,
                    'secret': secret_key,
                    'enableRateLimit': True,
                    'options': {'defaultType': 'future'}
                })
            
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
                with open(self.config_path, 'r') as f:
                    state = json.load(f)
                
                # Check if state is from today
                last_date = datetime.fromisoformat(state.get('date', '2000-01-01'))
                if last_date.date() == datetime.now().date():
                    self.daily_trade_count = state.get('daily_trade_count', 0)
                    self.daily_pnl = state.get('daily_pnl', 0.0)
                    self.last_trade_time = datetime.fromisoformat(state.get('last_trade_time')) if state.get('last_trade_time') else None
                    self.trades_history = state.get('trades_history', [])
                    print(f"Loaded today's state: {self.daily_trade_count} trades, ${self.daily_pnl} PnL")
                else:
                    print("New trading day, resetting state")
            except Exception as e:
                print(f"Error loading state: {e}")
    
    def _save_state(self):
        """Save current trading state to file."""
        state = {
            'date': datetime.now().isoformat(),
            'daily_trade_count': self.daily_trade_count,
            'daily_pnl': self.daily_pnl,
            'last_trade_time': self.last_trade_time.isoformat() if self.last_trade_time else None,
            'trades_history': self.trades_history
        }
        
        with open(self.config_path, 'w') as f:
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
            return {"allowed": False, "reason": f"Max daily trades ({self.max_trades_per_day}) reached"}
        
        # Check cooldown period
        if self.last_trade_time and now < self.last_trade_time + timedelta(minutes=self.cooldown_minutes):
            cooldown_ends = self.last_trade_time + timedelta(minutes=self.cooldown_minutes)
            wait_mins = (cooldown_ends - now).total_seconds() / 60
            return {"allowed": False, "reason": f"Cooldown period active. Wait {wait_mins:.1f} more minutes"}
        
        # Check daily loss limit
        if self.daily_pnl <= -self.max_daily_loss:
            return {"allowed": False, "reason": f"Daily loss limit (${self.max_daily_loss}) reached"}
        
        return {"allowed": True, "reason": "Trading allowed"}
    
    def format_symbol_for_exchange(self, symbol: str) -> str:
        """Format symbol according to exchange requirements."""
        # CoinEx uses specific symbol formats for futures/swaps
        if self.exchange_id == 'coinex':
            # CoinEx swap markets are typically in the format BTCUSDT or similar without '/'
            if '/' in symbol:
                # Convert BTC/USDT to BTCUSDT format
                formatted_symbol = symbol.replace('/', '')
                
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
            if hasattr(self.exchange, 'has'):
                print(f"Exchange capabilities: {self.exchange.has}")
                
            return True
        except Exception as e:
            print(f"Error checking order types: {e}")
            return False
    
    def place_trade(self, symbol: str, side: str, amount: float, price: float = None, 
                    stop_loss: float = None, take_profit: float = None, 
                    leverage: int = 5, margin_mode: str = 'isolated', 
                    post_only: bool = False) -> Dict:
        """
        Place a trade with risk management and advanced order features.
        
        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            side: 'buy' or 'sell'
            amount: Position size in USD
            price: Optional limit price
            stop_loss: Optional stop loss price
            take_profit: Optional take profit price
            leverage: Leverage multiplier (1-100 depending on exchange)
            margin_mode: 'isolated' or 'cross'
            post_only: If True, ensure order is maker only
        """
        # Check risk parameters
        trade_check = self.can_trade()
        if not trade_check["allowed"]:
            print(f"Trade rejected: {trade_check['reason']}")
            return {"success": False, "message": trade_check["reason"]}
        
        # Check position size
        if amount > self.max_position_size:
            return {"success": False, "message": f"Position size (${amount}) exceeds maximum (${self.max_position_size})"}
        
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
                return {"success": False, "message": f"Symbol not found or not supported: {formatted_symbol}. Error: {str(e)}"}
            
            # Set leverage first
            try:
                self.exchange.set_leverage(leverage, formatted_symbol)
                print(f"Set leverage to {leverage}x for {formatted_symbol}")
            except Exception as e:
                print(f"Warning: Could not set leverage - {str(e)}")
            
            # Set margin mode
            try:
                if self.exchange_id == 'coinex':
                    # CoinEx requires leverage parameter with margin mode
                    self.exchange.set_margin_mode(margin_mode, formatted_symbol, {'leverage': leverage})
                else:
                    self.exchange.set_margin_mode(margin_mode, formatted_symbol)
                print(f"Set margin mode to {margin_mode} for {formatted_symbol}")
            except Exception as e:
                print(f"Warning: Could not set margin mode - {str(e)}")
            
            # Calculate quantity based on current price if not specified
            if not price:
                try:
                    ticker = self.exchange.fetch_ticker(formatted_symbol)
                    price = ticker['last']
                except Exception as e:
                    return {"success": False, "message": f"Could not fetch price for {formatted_symbol}. Error: {str(e)}"}
            
            # Convert USD amount to actual quantity
            quantity = amount / price
            
            # Adjust for minimum quantity requirements
            if 'limits' in market and 'amount' in market['limits']:
                min_amount = market['limits']['amount']['min']
                if quantity < min_amount:
                    quantity = min_amount
                    print(f"Adjusted quantity to minimum: {quantity}")
            
            # Place the order
            order_type = 'market' if price is None else 'limit'
            
            # Exchange-specific order parameters
            if self.exchange_id == 'coinex':
                # For CoinEx swap
                order_params = {
                    'leverage': leverage,
                }
                
                # Add post-only parameter if requested
                if post_only and order_type == 'limit':
                    order_params['timeInForce'] = 'PO'  # Post Only
            else:
                order_params = {'type': 'future'}
                if post_only and order_type == 'limit':
                    order_params['postOnly'] = True
            
            # Place the actual order
            if order_type == 'limit':
                order = self.exchange.create_order(formatted_symbol, order_type, side, quantity, price, order_params)
            else:
                order = self.exchange.create_order(formatted_symbol, order_type, side, quantity, None, order_params)
            
            results = {
                "success": True, 
                "order": order, 
                "message": f"Successfully placed {side} order for {formatted_symbol}"
            }
            
            # Handle stop loss (always as market order)
            if stop_loss:
                stop_side = 'sell' if side == 'buy' else 'buy'
                try:
                    print(f"Attempting to place stop loss order: {stop_side} {quantity} at {stop_loss}")
                    
                    if self.exchange_id == 'coinex':
                        # CoinEx specific stop order implementation
                        stop_params = {
                            'stopPrice': stop_loss,
                            'type': 'stop_limit',  # CoinEx might use stop_limit instead of stop_market
                            'price': stop_loss,    # For stop_limit, we need a price too
                            'postOnly': False,
                            'reduceOnly': True
                        }
                        
                        stop_order = self.exchange.create_order(
                            formatted_symbol,
                            'stop_limit',  # Change to stop_limit for CoinEx
                            stop_side,
                            quantity,
                            stop_loss,     # Need to provide price for stop_limit
                            stop_params
                        )
                    else:
                        stop_params = {'stopPrice': stop_loss, 'reduceOnly': True}
                        stop_order = self.exchange.create_order(
                            formatted_symbol,
                            'stop_market',
                            stop_side,
                            quantity,
                            None,
                            stop_params
                        )

                    print(f"Stop loss order placed successfully: {stop_order}")
                except Exception as e:
                    print(f"Failed to place stop loss order: {str(e)}")

            # Handle take profit (always as limit order)
            if take_profit:
                tp_side = 'sell' if side == 'buy' else 'buy'
                try:
                    print(f"Attempting to place take profit order: {tp_side} {quantity} at {take_profit}")
                    
                    if self.exchange_id == 'coinex':
                        # CoinEx specific parameters for take profit
                        tp_params = {
                            'reduceOnly': True,
                            'postOnly': post_only if post_only else False
                        }
                    else:
                        tp_params = {'reduceOnly': True}
                        if post_only:
                            tp_params['postOnly'] = True
                    
                    tp_order = self.exchange.create_order(
                        formatted_symbol,
                        'limit',
                        tp_side,
                        quantity,
                        take_profit,
                        tp_params
                    )
                    print(f"Take profit order placed successfully: {tp_order}")
                    results["take_profit_order"] = tp_order
                    results["message"] += f" and take profit at {take_profit}"
                except Exception as e:
                    error_msg = str(e)
                    print(f"Take profit error: {error_msg}")  # This goes to terminal
                    results["take_profit_error"] = error_msg
                    results["message"] += f". Failed to set take profit: {error_msg}"

            # Update state
            self.last_trade_time = datetime.now()
            self.daily_trade_count += 1

            # Record trade
            trade_record = {
                "time": self.last_trade_time.isoformat(),
                "symbol": formatted_symbol,
                "side": side,
                "amount": amount,
                "price": price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "leverage": leverage,
                "margin_mode": margin_mode,
                "post_only": post_only,
                "order_id": order.get('id', 'unknown')
            }
            self.trades_history.append(trade_record)
            
            # Save state
            self._save_state()
            
            return results
            
        except Exception as e:
            error_msg = str(e)
            # Check for common exchange-specific errors
            if "balance" in error_msg.lower():
                return {"success": False, "message": f"Insufficient balance. Error: {error_msg}"}
            elif "permission" in error_msg.lower():
                return {"success": False, "message": f"API permission issue. Make sure your API key has trading permissions. Error: {error_msg}"}
            elif "symbol" in error_msg.lower():
                return {"success": False, "message": f"Symbol error. The pair {symbol} may not be available for futures trading. Error: {error_msg}"}
            else:
                return {"success": False, "message": f"Error placing trade: {self.exchange_id} {error_msg}"}
    
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
            print(f"WARNING: Daily loss limit of ${self.max_daily_loss} has been reached. Trading stopped for today.")
        
        self._save_state()
    
    def get_trading_status(self) -> Dict:
        """Get current trading status and risk metrics."""
        can_trade_result = self.can_trade()
        
        return {
            "exchange": self.exchange_id,
            "date": datetime.now().isoformat(),
            "can_trade": can_trade_result["allowed"],
            "status_message": can_trade_result["reason"],
            "daily_trade_count": self.daily_trade_count,
            "max_trades_per_day": self.max_trades_per_day,
            "trades_remaining": max(0, self.max_trades_per_day - self.daily_trade_count),
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_loss_limit": self.max_daily_loss,
            "max_position_size": self.max_position_size,
            "last_trade_time": self.last_trade_time.isoformat() if self.last_trade_time else None,
            "cooldown_ends": (self.last_trade_time + timedelta(minutes=self.cooldown_minutes)).isoformat() if self.last_trade_time else None
        }
    
    def get_open_positions(self) -> List[Dict]:
        """Get all open futures positions."""
        try:
            if self.exchange_id == 'coinex':
                # CoinEx might require specific method or endpoint
                positions = self.exchange.fetch_positions()
                return [p for p in positions if float(p.get('contracts', 0)) > 0]
            else:
                positions = self.exchange.fetch_positions()
                return [p for p in positions if float(p.get('contracts', 0)) > 0]
        except Exception as e:
            print(f"Error fetching positions: {e}")
            return []
    
    def close_position(self, symbol: str) -> Dict:
        """Close an open position for a symbol."""
        try:
            # Format symbol for the exchange
            formatted_symbol = self.format_symbol_for_exchange(symbol)
            
            positions = self.get_open_positions()
            position = next((p for p in positions if p['symbol'] == formatted_symbol), None)
            
            if not position:
                return {"success": False, "message": f"No open position found for {formatted_symbol}"}
            
            # Determine close direction (opposite of position)
            side = 'sell' if position['side'] == 'long' else 'buy'
            amount = abs(float(position['contracts']))
            
            # Place closing order with exchange-specific parameters
            if self.exchange_id == 'coinex':
                order = self.exchange.create_order(
                    formatted_symbol, 
                    'market', 
                    side, 
                    amount, 
                    None, 
                    {'reduceOnly': True}
                )
            else:
                order = self.exchange.create_order(
                    formatted_symbol, 
                    'market', 
                    side, 
                    amount, 
                    None, 
                    {'reduceOnly': True, 'type': 'future'}
                )
            
            return {"success": True, "order": order, "message": f"Successfully closed position for {formatted_symbol}"}
            
        except Exception as e:
            return {"success": False, "message": f"Error closing position: {str(e)}"}
    
    def update_risk_parameters(self, max_trades=None, cooldown_mins=None, max_daily_loss=None, max_position_size=None):
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
            "max_position_size": self.max_position_size
        }


def main():
    parser = argparse.ArgumentParser(description='Crypto Futures Trader with Risk Management')
    parser.add_argument('--exchange', type=str, required=True, help='Exchange ID (e.g., coinex, binance)')
    parser.add_argument('--config', type=str, default='trader_config.json', help='Path to config file')
    parser.add_argument('--apikey', type=str, required=True, help='API Key')
    parser.add_argument('--secret', type=str, required=True, help='Secret Key')
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Get trading status')
    
    # Trade command
    trade_parser = subparsers.add_parser('trade', help='Place a trade')
    trade_parser.add_argument('--symbol', type=str, required=True, help='Trading pair (e.g., BTC/USDT)')
    trade_parser.add_argument('--side', type=str, required=True, choices=['buy', 'sell'], help='Trade direction')
    trade_parser.add_argument('--amount', type=float, required=True, help='Position size in USD')
    trade_parser.add_argument('--price', type=float, help='Limit price (optional, market order if not specified)')
    trade_parser.add_argument('--stop-loss', type=float, help='Stop loss price')
    trade_parser.add_argument('--take-profit', type=float, help='Take profit price')
    trade_parser.add_argument('--leverage', type=int, default=5, help='Leverage multiplier')
    trade_parser.add_argument('--margin-mode', type=str, default='isolated', choices=['isolated', 'cross'], help='Margin mode')
    trade_parser.add_argument('--post-only', action='store_true', help='Make order post-only (limit orders only)')
    
    # Close position command
    close_parser = subparsers.add_parser('close', help='Close an open position')
    close_parser.add_argument('--symbol', type=str, required=True, help='Trading pair to close')
    
    # Update PnL command
    pnl_parser = subparsers.add_parser('pnl', help='Update daily PnL')
    pnl_parser.add_argument('--amount', type=float, required=True, help='Profit/loss amount in USD')
    
    # Positions command
    positions_parser = subparsers.add_parser('positions', help='Get open positions')
    
    # Update risk parameters command
    risk_parser = subparsers.add_parser('risk', help='Update risk parameters')
    risk_parser.add_argument('--max-trades', type=int, help='Maximum trades per day')
    risk_parser.add_argument('--cooldown', type=int, help='Cooldown period in minutes')
    risk_parser.add_argument('--max-loss', type=float, help='Maximum daily loss in USD')
    risk_parser.add_argument('--max-size', type=float, help='Maximum position size in USD')
    
    args = parser.parse_args()
    
    # Initialize trader
    trader = CryptoFuturesTrader(args.exchange, args.apikey, args.secret, args.config)
    
    # Execute command
    if args.command == 'status':
        status = trader.get_trading_status()
        print(json.dumps(status, indent=2))
    
    elif args.command == 'trade':
        result = trader.place_trade(
            args.symbol, 
            args.side, 
            args.amount, 
            args.price,
            args.stop_loss,
            args.take_profit,
            args.leverage,
            args.margin_mode,
            args.post_only
        )
        print(json.dumps(result, indent=2))
    
    elif args.command == 'close':
        result = trader.close_position(args.symbol)
        print(json.dumps(result, indent=2))
    
    elif args.command == 'pnl':
        trader.update_pnl(args.amount)
        status = trader.get_trading_status()
        print(json.dumps(status, indent=2))
    
    elif args.command == 'positions':
        positions = trader.get_open_positions()
        print(json.dumps(positions, indent=2))
    
    elif args.command == 'risk':
        trader.update_risk_parameters(
            args.max_trades, 
            args.cooldown, 
            args.max_loss, 
            args.max_size
        )
        print(json.dumps(trader.get_risk_parameters(), indent=2))
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
