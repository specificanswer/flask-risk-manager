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
app.config["WTF_CSRF_ENABLED"] = False  # Disable CSRF for simplicity in this example


# Create simple form classes without flask_wtf dependency
class SimpleForm:
    def validate_on_submit(self):
        return request.method == "POST"


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
        return ""


# Form for closing positions
class ClosePositionForm(SimpleForm):
    def __init__(self):
        self.symbol = None
        self.submit = None

    def hidden_tag(self):
        return ""


# Form for updating PnL
class PnLForm(SimpleForm):
    def __init__(self):
        self.amount = None
        self.submit = None

    def hidden_tag(self):
        return ""


# Global trader instance
trader = None


@app.route("/")
def index():
    if trader is None:
        return redirect(url_for("setup"))

    # Start monitoring if not already active
    if not trader.monitoring_active:
        trader.start_monitoring()

    try:
        status = trader.get_trading_status()
        positions = trader.get_open_positions()

        # Create forms
        trade_form = TradeForm()
        close_form = ClosePositionForm()
        pnl_form = PnLForm()

        return render_template(
            "index.html",
            status=status,
            positions=positions,
            trade_form=trade_form,
            close_form=close_form,
            pnl_form=pnl_form,
        )
    except Exception as e:
        return handle_error("Dashboard Error", str(e), traceback.format_exc())


@app.route("/setup", methods=["GET", "POST"])
def setup():
    global trader

    if request.method == "POST":
        exchange_id = request.form["exchange"]
        api_key = request.form["api_key"]
        secret_key = request.form["secret_key"]
        config_path = request.form.get("config_path", "trader_config.json")

        try:
            trader = CryptoFuturesTrader(exchange_id, api_key, secret_key, config_path)
            flash("Successfully connected to exchange!", "success")
            return redirect(url_for("index"))
        except Exception as e:
            flash(f"Error connecting to exchange: {str(e)}", "danger")

    return render_template("setup.html")


@app.route("/trade", methods=["POST"])
def place_trade():
    if trader is None:
        return redirect(url_for("setup"))

    try:
        # Get form data
        symbol = request.form["symbol"]
        side = request.form["side"]
        amount = float(request.form["amount"])

        # Optional parameters
        price = (
            float(request.form["price"])
            if request.form.get("price") and request.form["price"].strip()
            else None
        )
        stop_loss = (
            float(request.form["stop_loss"])
            if request.form.get("stop_loss") and request.form["stop_loss"].strip()
            else None
        )
        take_profit = (
            float(request.form["take_profit"])
            if request.form.get("take_profit") and request.form["take_profit"].strip()
            else None
        )
        leverage = int(request.form.get("leverage", 5))
        margin_mode = request.form.get("margin_mode", "isolated")
        post_only = "post_only" in request.form

        # Validate order type and required fields
        order_type = request.form.get("order_type", "market")
        if order_type == "limit" and price is None:
            flash("Limit orders require a price", "danger")
            return redirect(url_for("index"))

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
            post_only=post_only,
        )

        if result["success"]:
            flash(f"Trade successful: {result['message']}", "success")
        else:
            flash(f"Trade failed: {result['message']}", "danger")

    except ValueError as e:
        flash(f"Invalid input: {str(e)}", "danger")
    except Exception as e:
        return handle_error("Trade Error", str(e), traceback.format_exc())

    return redirect(url_for("index"))


@app.route("/close", methods=["POST"])
def close_position():
    if trader is None:
        return redirect(url_for("setup"))

    try:
        symbol = request.form["symbol"]
        result = trader.close_position(symbol)

        if result["success"]:
            flash(f"Position closed: {result['message']}", "success")
        else:
            flash(f"Failed to close position: {result['message']}", "danger")
    except Exception as e:
        return handle_error("Close Position Error", str(e), traceback.format_exc())

    return redirect(url_for("index"))


@app.route("/pnl", methods=["POST"])
def update_pnl():
    if trader is None:
        return redirect(url_for("setup"))

    try:
        amount = float(request.form["amount"])
        trader.update_pnl(amount)
        flash(f"PnL updated: ${amount}", "success")
    except ValueError:
        flash("Please enter a valid number for PnL", "danger")
    except Exception as e:
        return handle_error("PnL Update Error", str(e), traceback.format_exc())

    return redirect(url_for("index"))


@app.route("/api/markets", methods=["GET"])
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
            if market.get("type") == "swap" or market.get("type") == "future":
                markets.append(
                    {
                        "symbol": symbol,
                        "base": market.get("base"),
                        "quote": market.get("quote"),
                        "type": market.get("type"),
                    }
                )

        return jsonify({"markets": markets})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ticker/<symbol>", methods=["GET"])
def get_ticker(symbol):
    """API endpoint to get current ticker data for a symbol"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400

    try:
        ticker = trader.exchange.fetch_ticker(symbol)
        return jsonify(
            {
                "symbol": symbol,
                "last": ticker.get("last"),
                "bid": ticker.get("bid"),
                "ask": ticker.get("ask"),
                "high": ticker.get("high"),
                "low": ticker.get("low"),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/status", methods=["GET"])
def get_status():
    """API endpoint to get current trading status"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400

    try:
        status = trader.get_trading_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/positions", methods=["GET"])
def get_positions():
    """API endpoint to get current open positions"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400

    try:
        positions = trader.get_open_positions()
        return jsonify({"positions": positions})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/leverage/<symbol>", methods=["POST"])
def set_leverage(symbol):
    """API endpoint to set leverage for a symbol"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400

    try:
        leverage = int(request.json.get("leverage", 5))
        result = trader.exchange.set_leverage(leverage, symbol)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/margin_mode/<symbol>", methods=["POST"])
def set_margin_mode(symbol):
    """API endpoint to set margin mode for a symbol"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400

    try:
        margin_mode = request.json.get("margin_mode", "isolated")
        result = trader.exchange.set_margin_mode(margin_mode, symbol)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/history", methods=["GET"])
def get_trade_history():
    """API endpoint to get trade history"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400

    try:
        return jsonify({"trades": trader.trades_history})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/monitoring_status", methods=["GET"])
def monitoring_status():
    """Get monitoring system status"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400

    try:
        status = trader.get_monitoring_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/debug_monitors", methods=["GET"])
def debug_monitors():
    """Debug monitoring system"""
    if trader is None:
        return jsonify({"error": "Not connected to exchange"}), 400

    try:
        monitors = trader.debug_monitors()
        return jsonify({"monitors": monitors})
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
        "error.html",
        error_title=title,
        error_message=message,
        error_details=details,
        show_setup_button=show_setup_button,
    ), (500 if title != "Page Not Found" else 404)


def main():
    parser = argparse.ArgumentParser(
        description="Web interface for Crypto Futures Trader"
    )
    parser.add_argument(
        "--host", type=str, default="0.0.0.0", help="Host address to bind"
    )
    parser.add_argument("--port", type=int, default=5000, help="Port to bind")
    parser.add_argument("--debug", action="store_true", help="Run in debug mode")

    args = parser.parse_args()

    try:
        app.run(host=args.host, port=args.port, debug=args.debug)
    except Exception as e:
        print(f"Error starting application: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
