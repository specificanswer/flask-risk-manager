import flask
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import json
import os
import sys
import traceback
from datetime import datetime, timedelta
import argparse

# Import our enhanced trader class
from coinex_trader import CryptoFuturesTrader

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for simplicity in this example

# Create simple form classes without flask_wtf dependency
class SimpleForm:
    def validate_on_submit(self):
        return request.method == 'POST'

# Form for placing trades with advanced options
class TradeForm(SimpleForm):
    def __init__(self):
        self.symbol = None
        self.side = None
        self.amount = None
        self.price = None
        self.stop_loss = None
        self.take_profit = None
        self.leverage = None
        self.margin_mode = None
        self.post_only = None
        self.errors = {}
    
    def hidden_tag(self):
        return ''

# Form for closing positions
class ClosePositionForm(SimpleForm):
    def __init__(self):
        self.symbol = None
        self.submit = None
    
    def hidden_tag(self):
        return ''

# Form for updating PnL
class PnLForm(SimpleForm):
    def __init__(self):
        self.amount = None
        self.submit = None
    
    def hidden_tag(self):
        return ''

# Global trader instance
trader = None

@app.route('/')
def index():
    if trader is None:
        return redirect(url_for('setup'))
        
    try:
        # Check pending orders status first
        if trader:
            trader.check_pending_orders()
            
        status = trader.get_trading_status()
        positions = trader.get_open_positions()
        pending_orders = trader.get_pending_orders()
        
        # Create forms
        trade_form = TradeForm()
        close_form = ClosePositionForm()
        pnl_form = PnLForm()
        
        return render_template(
            'index.html',
            status=status,
            positions=positions,
            pending_orders=pending_orders,
            trade_form=trade_form,
            close_form=close_form,
            pnl_form=pnl_form,
            default_symbol="SOL/USDT"  # Default symbol set to SOL/USDT
        )
    except Exception as e:
        return handle_error("Dashboard Error", str(e), traceback.format_exc())

@app.route('/dashboard')
def dashboard():
    """
    Modern dashboard with trading panel
    """
    if trader is None:
        return redirect(url_for('setup'))
        
    try:
        # Check pending orders status first
        if trader:
            trader.check_pending_orders()
            
        status = trader.get_trading_status()
        positions = trader.get_open_positions()
        pending_orders = trader.get_pending_orders()
        
        # Get available symbols
        symbols = []
        try:
            # Try to get markets from the exchange
            markets = trader.exchange.markets
            for symbol, market in markets.items():
                if market.get('type') == 'swap' or market.get('type') == 'future':
                    symbols.append(symbol)
        except Exception as e:
            # Default symbols if exchange request fails
            symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
        
        return render_template(
            'dashboard.html',
            status=status,
            positions=positions,
            pending_orders=pending_orders,
            symbols=symbols
        )
    except Exception as e:
        return handle_error("Dashboard Error", str(e), traceback.format_exc())

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    global trader
    
    if request.method == 'POST':
        exchange_id = request.form['exchange']
        api_key = request.form['api_key']
        secret_key = request.form['secret_key']
        config_path = request.form.get('config_path', 'trader_config.json')
        
        try:
            trader = CryptoFuturesTrader(exchange_id, api_key, secret_key, config_path)
            flash('Successfully connected to exchange!', 'success')
            return redirect(url_for('dashboard'))  # Redirect to new dashboard
        except Exception as e:
            flash(f'Error connecting to exchange: {str(e)}', 'danger')
    
    return render_template('setup.html')

@app.route('/trade', methods=['POST'])
def place_trade():
    if trader is None:
        return redirect(url_for('setup'))
    
    try:
        # Get form data
        symbol = request.form['symbol']
        side = request.form['side']
        amount = float(request.form['amount'])
        
        # Optional parameters
        price = float(request.form['price']) if request.form.get('price') and request.form['price'].strip() else None
        stop_loss = float(request.form['stop_loss']) if request.form.get('stop_loss') and request.form['stop_loss'].strip() else None
        take_profit = float(request.form['take_profit']) if request.form.get('take_profit') and request.form['take_profit'].strip() else None
        leverage = int(request.form.get('leverage', 5))
        margin_mode = request.form.get('margin_mode', 'isolated')
        post_only = 'post_only' in request.form
        
        # Validate order type and required fields
        order_type = request.form.get('order_type', 'market')
        if order_type == 'limit' and price is None:
            flash("Limit orders require a price", 'danger')
            return redirect(url_for('index'))
        
        # Place the trade with all parameters
        result = trader.place_trade(
            symbol=symbol,
            side=side,
            amount=amount,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            leverage=leverage,
            margin_mode=margin_mode,
            post_only=post_only
        )
        
        if result['success']:
            order_type_desc = "market" if order_type == "market" else "limit"
            if order_type == "limit":
                flash(f"Order placed: {result['message']} (pending fill)", 'success')
            else:
                flash(f"Trade successful: {result['message']}", 'success')
        else:
            flash(f"Trade failed: {result['message']}", 'danger')
            
    except ValueError as e:
        flash(f"Invalid input: {str(e)}", 'danger')
    except Exception as e:
        return handle_error("Trade Error", str(e), traceback.format_exc())
    
    return redirect(url_for('index'))

@app.route('/place_trade', methods=['POST'])
def api_place_trade():
    """
    API endpoint for placing trades from the trading panel
    """
    if trader is None:
        return jsonify({"success": False, "message": "Trading system not initialized"}), 400
    
    try:
        # Get request data
        data = request.json
        
        # Extract parameters
        symbol = data.get('symbol')
        side = data.get('side')
        amount = float(data.get('amount'))
        order_type = data.get('order_type')
        
        # Optional parameters
        price = float(data.get('price')) if data.get('price') else None
        stop_loss = float(data.get('stop_loss')) if data.get('stop_loss') else None
        take_profit = float(data.get('take_profit')) if data.get('take_profit') else None
        leverage = int(data.get('leverage', 5))
        margin_mode = data.get('margin_mode', 'isolated')
        post_only = bool(data.get('post_only', False))
        
        # Validate order type and required fields
        if order_type == 'limit' and price is None:
            return jsonify({
                "success": False,
                "message": "Limit orders require a price"
            })
        
        # Place the trade with all parameters
        result = trader.place_trade(
            symbol=symbol,
            side=side,
            amount=amount,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            leverage=leverage,
            margin_mode=margin_mode,
            post_only=post_only
        )
        
        # Format the response
        if result.get('success'):
            return jsonify({
                "success": True,
                "message": result.get('message'),
                "order_id": result.get('order', {}).get('id')
            })
        else:
            return jsonify({
                "success": False,
                "message": result.get('message')
            })
    except ValueError as e:
        return jsonify({"success": False, "message": f"Invalid input: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

@app.route('/cancel_order/<order_id>', methods=['POST'])
def cancel_order(order_id):
    if trader is None:
        return redirect(url_for('setup'))
    
    try:
        result = trader.cancel_order(order_id)
        
        if result['success']:
            flash(f"Order canceled: {result['message']}", 'success')
        else:
            flash(f"Failed to cancel order: {result['message']}", 'danger')
    except Exception as e:
        return handle_error("Cancel Order Error", str(e), traceback.format_exc())
    
    return redirect(url_for('index'))

@app.route('/close', methods=['POST'])
def close_position():
    if trader is None:
        return redirect(url_for('setup'))
    
    try:
        symbol = request.form['symbol']
        result = trader.close_position(symbol)
        
        if result['success']:
            flash(f"Position closed: {result['message']}", 'success')
        else:
            flash(f"Failed to close position: {result['message']}", 'danger')
    except Exception as e:
        return handle_error("Close Position Error", str(e), traceback.format_exc())
    
    return redirect(url_for('index'))

@app.route('/close_position', methods=['POST'])
def api_close_position():
    """
    API endpoint to close a position from the trading panel
    """
    if trader is None:
        return jsonify({"success": False, "message": "Trading system not initialized"}), 400
    
    try:
        # Get request data
        data = request.json
        symbol = data.get('symbol')
        
        if not symbol:
            return jsonify({"success": False, "message": "Symbol is required"}), 400
        
                # Close the position with auto_liquidation flag
        result = trader.close_position(symbol, auto_liquidation)
        
        # Format the response
        if result.get('success'):
            return jsonify({
                "success": True,
                "message": result.get('message'),
                "auto_liquidation": auto_liquidation
            })
        else:
            return jsonify({
                "success": False,
                "message": result.get('message')
            })
    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

@app.route('/api/check_auto_liquidation', methods=['GET'])
def api_check_auto_liquidation():
    """API endpoint to check if positions need auto-liquidation"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400
    
    try:
        positions = trader.get_open_positions()
        liquidated_positions = []
        
        for position in positions:
            unrealized_pnl = float(position.get('unrealizedPnl', 0))
        
        # Format the response
        if result.get('success'):
            return jsonify({
                "success": True,
                "message": result.get('message')
            })
        else:
            return jsonify({
                "success": False,
                "message": result.get('message')
            })
    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

@app.route('/pnl', methods=['POST'])
def update_pnl():
    if trader is None:
        return redirect(url_for('setup'))
    
    try:
        amount = float(request.form['amount'])
        trader.update_pnl(amount)
        flash(f"PnL updated: ${amount}", 'success')
    except ValueError:
        flash("Please enter a valid number for PnL", 'danger')
    except Exception as e:
        return handle_error("PnL Update Error", str(e), traceback.format_exc())
    
    return redirect(url_for('index'))

@app.route('/api/markets', methods=['GET'])
def get_markets():
    """API endpoint to get available markets for the selected exchange"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400
    
    try:
        # Ensure markets are loaded
        if not trader.exchange.markets:
            trader.exchange.load_markets()
        
        # Get all futures markets
        markets = []
        for symbol, market in trader.exchange.markets.items():
            if market.get('type') == 'swap' or market.get('type') == 'future':
                markets.append({
                    'symbol': symbol,
                    'base': market.get('base'),
                    'quote': market.get('quote'),
                    'type': market.get('type')
                })
        
        return jsonify({"markets": markets})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/ticker/<symbol>', methods=['GET'])
def get_ticker(symbol):
    """API endpoint to get current ticker data for a symbol"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400
    
    try:
        # Format symbol for exchange if needed
        formatted_symbol = trader.format_symbol_for_exchange(symbol)
        
        # Fetch ticker data
        ticker = trader.exchange.fetch_ticker(formatted_symbol)
        
        return jsonify({
            "symbol": formatted_symbol,
            "last": ticker.get('last'),
            "bid": ticker.get('bid'),
            "ask": ticker.get('ask'),
            "high": ticker.get('high'),
            "low": ticker.get('low'),
            "volume": ticker.get('volume')
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    """API endpoint to get current trading status"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400
    
    try:
        status = trader.get_trading_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/positions', methods=['GET'])
def get_positions():
    """API endpoint to get current open positions"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400
    
    try:
        trader.check_pending_orders()  # Check pending orders first
        positions = trader.get_open_positions()
        return jsonify({"positions": positions})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/pending', methods=['GET'])
def get_pending_orders():
    """API endpoint to get pending orders"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400
    
    try:
        trader.check_pending_orders()  # Update status first
        pending = trader.get_pending_orders()
        return jsonify({"pending_orders": pending})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/set_position_orders/<symbol>', methods=['POST'])
def set_position_orders(symbol):
    """API endpoint to set stop loss and take profit for an existing position"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400
    
    try:
        data = request.json
        side = data.get('side')
        quantity = float(data.get('quantity'))
        stop_loss = float(data.get('stop_loss')) if data.get('stop_loss') else None
        take_profit = float(data.get('take_profit')) if data.get('take_profit') else None
        post_only = data.get('post_only', False)
        
        result = trader.set_position_orders(
            symbol,
            side,
            quantity,
            stop_loss,
            take_profit,
            post_only
        )
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/leverage/<symbol>', methods=['POST'])
def set_leverage(symbol):
    """API endpoint to set leverage for a symbol"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400
    
    try:
        leverage = int(request.json.get('leverage', 5))
        result = trader.exchange.set_leverage(leverage, symbol)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/margin_mode/<symbol>', methods=['POST'])
def set_margin_mode(symbol):
    """API endpoint to set margin mode for a symbol"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400
    
    try:
        margin_mode = request.json.get('margin_mode', 'isolated')
        result = trader.exchange.set_margin_mode(margin_mode, symbol)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/history', methods=['GET'])
def get_trade_history():
    """API endpoint to get trade history"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400
    
    try:
        return jsonify({"trades": trader.trades_history})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/refresh_data', methods=['GET'])
def refresh_data():
    """API endpoint to refresh all data"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400
    
    try:
        # Check pending orders first
        trader.check_pending_orders()
        
        # Get updated data
        status = trader.get_trading_status()
        positions = trader.get_open_positions()
        pending_orders = trader.get_pending_orders()
        
        return jsonify({
            "status": status,
            "positions": positions,
            "pending_orders": pending_orders
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def page_not_found(e):
    """Handle 404 errors"""
    return handle_error("Page Not Found", "The requested page could not be found.")

@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors"""
    return handle_error("Server Error", "An internal server error occurred.")

def handle_error(title, message, details=None):
    """Render error page with details"""
    show_setup_button = trader is None
    return render_template(
        'error.html',
        error_title=title,
        error_message=message,
        error_details=details,
        show_setup_button=show_setup_button
    ), 500 if title != "Page Not Found" else 404

def main():
    parser = argparse.ArgumentParser(description='Web interface for Crypto Futures Trader')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host address to bind')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind')
    parser.add_argument('--debug', action='store_true', help='Run in debug mode')
    
    args = parser.parse_args()
    
    try:
        app.run(host=args.host, port=args.port, debug=args.debug)
    except Exception as e:
        print(f"Error starting application: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()

# Add these routes to your web_interface.py file

@app.route('/api/position_details/<symbol>', methods=['GET'])
def api_position_details(symbol):
    """API endpoint to get detailed position info including SL/TP"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400
    
    try:
        # Format symbol for exchange if needed
        formatted_symbol = trader.format_symbol_for_exchange(symbol)
        
        # Get position
        positions = trader.get_open_positions()
        position = next((p for p in positions if p['symbol'] == formatted_symbol), None)
        
        # Try different symbol formats if not found
        if not position and ':USDT' not in formatted_symbol:
            position = next((p for p in positions if p['symbol'] == f"{formatted_symbol}:USDT"), None)
            if position:
                formatted_symbol = position['symbol']
        
        if not position and '-USDT' not in formatted_symbol:
            position = next((p for p in positions if p['symbol'] == f"{formatted_symbol}-USDT"), None)
            if position:
                formatted_symbol = position['symbol']
        
        if not position:
            return jsonify({"error": f"No position found for {symbol}"}), 404
        
        # Get any existing stop loss and take profit orders
        stop_loss = None
        take_profit = None
        
        try:
            open_orders = trader.exchange.fetch_open_orders(formatted_symbol)
            
            for order in open_orders:
                # Logic to identify stop loss orders
                if order.get('type') == 'stop' or order.get('type') == 'stop_market':
                    if (position['side'] == 'long' and order.get('side') == 'sell') or \
                       (position['side'] == 'short' and order.get('side') == 'buy'):
                        stop_loss = order.get('stopPrice') or order.get('price')
                
                # Logic to identify take profit orders
                if order.get('type') == 'limit':
                    if (position['side'] == 'long' and order.get('side') == 'sell') or \
                       (position['side'] == 'short' and order.get('side') == 'buy'):
                        take_profit = order.get('price')
        except Exception as e:
            print(f"Warning: Could not fetch open orders: {e}")
        
        # Return complete position details
        return jsonify({
            "symbol": position['symbol'],
            "side": position['side'],
            "size": position['contracts'],
            "entryPrice": position['entryPrice'],
            "leverage": position['leverage'],
            "unrealizedPnl": position['unrealizedPnl'],
            "stopLoss": stop_loss,
            "takeProfit": take_profit
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/set_position_orders', methods=['POST'])
def api_set_position_orders():
    """API endpoint to set stop loss and take profit for an existing position"""
    if trader is None:
        return jsonify({"success": False, "message": "Trading system not initialized"}), 400
    
    try:
        data = request.json
        symbol = data.get('symbol')
        side = data.get('side')
        quantity = float(data.get('quantity'))
        stop_loss = float(data.get('stop_loss')) if data.get('stop_loss') else None
        take_profit = float(data.get('take_profit')) if data.get('take_profit') else None
        
        # Cancel any existing SL/TP orders first
        try:
            # Format symbol for exchange if needed
            formatted_symbol = trader.format_symbol_for_exchange(symbol)
            
            # Get any existing orders
            open_orders = trader.exchange.fetch_open_orders(formatted_symbol)
            for order in open_orders:
                # Only cancel stop loss and take profit orders
                if order.get('type') in ['stop', 'stop_market', 'limit'] and order.get('reduceOnly', False):
                    trader.exchange.cancel_order(order['id'], formatted_symbol)
                    print(f"Canceled existing SL/TP order: {order['id']}")
        except Exception as e:
            print(f"Warning: Could not cancel existing orders: {e}")
        
        # Set new orders
        result = trader.set_position_orders(
            symbol,
            side,
            quantity,
            stop_loss,
            take_profit,
            False  # post_only set to False
        )
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/close_position', methods=['POST'])
def api_close_position():
    """API endpoint to close a position from the trading panel"""
    if trader is None:
        return jsonify({"success": False, "message": "Trading system not initialized"}), 400
    
    try:
        # Get request data
        data = request.json
        symbol = data.get('symbol')
        auto_liquidation = data.get('auto_liquidation', False)
        
        if not symbol:
            return jsonify({"success": False, "message": "Symbol is required"}), 400
        
        # Close the position with auto_liquidation flag
        result = trader.close_position(symbol, auto_liquidation)
        
        # Format the response
        if result.get('success'):
            return jsonify({
                "success": True,
                "message": result.get('message'),
                "auto_liquidation": auto_liquidation
            })
        else:
            return jsonify({
                "success": False,
                "message": result.get('message')
            })
    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

@app.route('/api/check_auto_liquidation', methods=['GET'])
def api_check_auto_liquidation():
    """API endpoint to check if positions need auto-liquidation"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400
    
    try:
        positions = trader.get_open_positions()
        liquidated_positions = []
        
        for position in positions:
            unrealized_pnl = float(position.get('unrealizedPnl', 0))
            
            # Check if position needs to be liquidated (-$5 threshold)
            if unrealized_pnl <= -5:
                symbol = position['symbol']
                result = trader.close_position(symbol, True)  # Auto-liquidation
                
                if result.get('success'):
                    liquidated_positions.append({
                        "symbol": symbol,
                        "unrealizedPnl": unrealized_pnl,
                        "message": result.get('message')
                    })
        
        return jsonify({
            "checked": len(positions),
            "liquidated": liquidated_positions
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Add these updated endpoints to your web_interface.py file

@app.route('/api/set_position_orders', methods=['POST'])
def api_set_position_orders():
    """API endpoint to set stop loss and take profit for an existing position"""
    if trader is None:
        return jsonify({"success": False, "message": "Trading system not initialized"}), 400
    
    try:
        data = request.json
        symbol = data.get('symbol')
        side = data.get('side')
        quantity = float(data.get('quantity'))
        stop_loss = float(data.get('stop_loss')) if data.get('stop_loss') else None
        take_profit = float(data.get('take_profit')) if data.get('take_profit') else None
        
        # Format symbol for exchange if needed
        symbol = trader.format_symbol_for_exchange(symbol)
        
        result = trader.set_position_orders(
            symbol,
            side,
            quantity,
            stop_loss,
            take_profit,
            False  # post_only set to False
        )
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/position_details/<symbol>', methods=['GET'])
def api_position_details(symbol):
    """API endpoint to get detailed position info including SL/TP"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400
    
    try:
        # Format symbol for exchange if needed
        formatted_symbol = trader.format_symbol_for_exchange(symbol)
        
        # Get position
        positions = trader.get_open_positions()
        position = next((p for p in positions if p['symbol'] == formatted_symbol), None)
        
        if not position:
            return jsonify({"error": f"No position found for {symbol}"}), 404
        
        # Get any existing stop loss and take profit orders
        open_orders = trader.exchange.fetch_open_orders(formatted_symbol)
        
        stop_loss = None
        take_profit = None
        
        for order in open_orders:
            # Logic to identify stop loss orders
            if order.get('type') == 'stop' or order.get('type') == 'stop_market':
                if (position['side'] == 'long' and order.get('side') == 'sell') or \
                   (position['side'] == 'short' and order.get('side') == 'buy'):
                    stop_loss = order.get('stopPrice') or order.get('price')
            
            # Logic to identify take profit orders
            if order.get('type') == 'limit':
                if (position['side'] == 'long' and order.get('side') == 'sell') or \
                   (position['side'] == 'short' and order.get('side') == 'buy'):
                    take_profit = order.get('price')
        
        # Return complete position details
        return jsonify({
            "symbol": position['symbol'],
            "side": position['side'],
            "size": position['contracts'],
            "entryPrice": position['entryPrice'],
            "leverage": position['leverage'],
            "unrealizedPnl": position['unrealizedPnl'],
            "stopLoss": stop_loss,
            "takeProfit": take_profit
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/close_position', methods=['POST'])
def api_close_position():
    """API endpoint to close a position from the trading panel"""
    if trader is None:
        return jsonify({"success": False, "message": "Trading system not initialized"}), 400
    
    try:
        # Get request data
        data = request.json
        symbol = data.get('symbol')
        auto_liquidation = data.get('auto_liquidation', False)
        
        if not symbol:
            return jsonify({"success": False, "message": "Symbol is required"}), 400
        
        # Format symbol for exchange if needed
        formatted_symbol = trader.format_symbol_for_exchange(symbol)
        
        # Close the position
        result = trader.close_position(formatted_symbol)
        
        # If this was an auto-liquidation, log it
        if auto_liquidation and result.get('success'):
            # You could add logging or tracking here
            print(f"AUTO-LIQUIDATION: Position {formatted_symbol} liquidated due to max loss rule")
        
        # Format the response
        if result.get('success'):
            return jsonify({
                "success": True,
                "message": result.get('message'),
                "auto_liquidation": auto_liquidation
            })
        else:
            return jsonify({
                "success": False,
                "message": result.get('message')
            })
    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

# Update the existing trader.close_position() method in coinex_trader.py to handle symbols better

def close_position(self, symbol: str) -> Dict:
    """Close an open position for a symbol."""
    try:
        # Get positions first to see if it exists
        positions = self.get_open_positions()
        
        # Try to match the position exactly
        position = next((p for p in positions if p['symbol'] == symbol), None)
        
        # If not found, try different format variations
        if not position:
            # Try without USDT suffix if it has one
            if symbol.endswith('USDT'):
                base_symbol = symbol[:-4]
                for p in positions:
                    if p['symbol'].startswith(base_symbol):
                        position = p
                        symbol = p['symbol']  # Use the correct symbol format
                        break
            
            # Try with :USDT suffix
            if not position and ':USDT' not in symbol:
                for p in positions:
                    if p['symbol'] == f"{symbol}:USDT":
                        position = p
                        symbol = p['symbol']
                        break
        
        if not position:
            return {"success": False, "message": f"No open position found for {symbol}"}
        
        # Determine close direction (opposite of position)
        side = 'sell' if position['side'] == 'long' else 'buy'
        amount = abs(float(position['contracts']))
        
        # Place closing order with exchange-specific parameters
        if self.exchange_id == 'coinex':
            order = self.exchange.create_order(
                symbol, 
                'market', 
                side, 
                amount, 
                None, 
                {'reduceOnly': True}
            )
        else:
            order = self.exchange.create_order(
                symbol, 
                'market', 
                side, 
                amount, 
                None, 
                {'reduceOnly': True, 'type': 'future'}
            )
        
        return {"success": True, "order": order, "message": f"Successfully closed position for {symbol}"}
        
    except Exception as e:
        return {"success": False, "message": f"Error closing position: {str(e)}"}
