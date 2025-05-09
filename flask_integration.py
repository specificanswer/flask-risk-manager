# Flask routes to integrate with the trading panel

@app.route('/dashboard')
def dashboard():
    """
    Main dashboard with trading panel
    """
    # Check if trader is initialized
    if trader is None:
        return redirect(url_for('setup'))
    
    try:
        # Get trading status
        status = trader.get_trading_status()
        
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
            symbols=symbols
        )
    except Exception as e:
        return handle_error("Dashboard Error", str(e), traceback.format_exc())

@app.route('/api/ticker/<symbol>')
def get_ticker(symbol):
    """
    API endpoint to get current price for a symbol
    """
    if trader is None:
        return jsonify({"error": "Trading system not initialized"}), 400
    
    try:
        # Clean the symbol format if needed
        symbol = trader.format_symbol_for_exchange(symbol)
        
        # Fetch ticker data
        ticker = trader.exchange.fetch_ticker(symbol)
        
        return jsonify({
            "symbol": symbol,
            "last": ticker.get('last'),
            "bid": ticker.get('bid'),
            "ask": ticker.get('ask'),
            "high": ticker.get('high'),
            "low": ticker.get('low'),
            "volume": ticker.get('volume')
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/place_trade', methods=['POST'])
def place_trade():
    """
    API endpoint to place a trade
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
        
        # Place the trade with your existing risk management logic
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

@app.route('/close_position', methods=['POST'])
def close_position():
    """
    API endpoint to close a position
    """
    if trader is None:
        return jsonify({"success": False, "message": "Trading system not initialized"}), 400
    
    try:
        # Get request data
        data = request.json
        symbol = data.get('symbol')
        
        if not symbol:
            return jsonify({"success": False, "message": "Symbol is required"}), 400
        
        # Close the position using your existing logic
        result = trader.close_position(symbol)
        
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

@app.route('/api/positions')
def get_positions():
    """
    API endpoint to get open positions
    """
    if trader is None:
        return jsonify({"error": "Trading system not initialized"}), 400
    
    try:
        # Get open positions using your existing trader class
        positions = trader.get_open_positions()
        
        return jsonify({"positions": positions})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Add a dashboard.html template in your templates folder
# This template should include the trading panel component:
# {% include 'trading_panel.html' %}
