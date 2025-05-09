// trading_panel.js - Updated with position size slider and position management fixes

document.addEventListener('DOMContentLoaded', function() {
  // DOM Elements
  const orderForm = document.getElementById('order-form');
  const symbolSelect = document.getElementById('symbol');
  const refreshPriceBtn = document.getElementById('refresh-price');
  const toggleButtons = document.querySelectorAll('.toggle-button');
  const orderTypeInput = document.getElementById('order-type-input');
  const priceGroup = document.querySelector('.price-group');
  const sideButtons = document.querySelectorAll('.side-button');
  const sideInput = document.getElementById('side-input');
  const positionSizeSlider = document.getElementById('position-size-slider');
  const positionSizeDisplay = document.getElementById('position-size-display');
  const positionSizePercent = document.getElementById('position-size-percent');
  const amountInput = document.getElementById('amount');
  const submitOrderBtn = document.getElementById('submit-order');
  const refreshPositionsBtn = document.getElementById('refresh-positions');
  const positionsContainer = document.getElementById('positions-container');
  const priceInput = document.getElementById('price');
  const stopLossInput = document.getElementById('stop_loss');
  const takeProfitInput = document.getElementById('take_profit');
  const leverageSelect = document.getElementById('leverage');
  
  // Position Control Modal Elements
  const positionControlModal = new bootstrap.Modal(document.getElementById('positionControlModal'));
  const positionSymbolInput = document.getElementById('position-symbol');
  const positionSideInput = document.getElementById('position-side');
  const positionSizeInput = document.getElementById('position-size');
  const positionStopLossInput = document.getElementById('position-stop-loss');
  const positionTakeProfitInput = document.getElementById('position-take-profit');
  const updatePositionButton = document.getElementById('update-position-button');
  const closePositionButton = document.getElementById('close-position-button');
  
  // Variables
  const maxPositionSize = parseFloat(amountInput.value) || 100; // Get from hidden input
  let cooldownEndTime = null; // Store cooldown end time
  let cooldownCheckInterval = null; // Interval to check cooldown status
  
  // Check cooldown status on page load
  checkCooldownStatus();
  
  // Position Size Slider
  positionSizeSlider.addEventListener('input', function() {
    const percent = parseInt(this.value);
    const amount = (maxPositionSize * percent / 100).toFixed(2);
    
    positionSizeDisplay.textContent = `$${amount}`;
    positionSizePercent.textContent = `${percent}%`;
    amountInput.value = amount;
    
    // Update calculations if price is set
    if (priceInput.value) {
      updateStopLossTakeProfit();
    }
  });
  
  // Toggle Order Type
  toggleButtons.forEach(button => {
    button.addEventListener('click', function() {
      toggleButtons.forEach(btn => btn.classList.remove('active'));
      this.classList.add('active');
      
      const orderType = this.getAttribute('data-value');
      orderTypeInput.value = orderType;
      
      if (orderType === 'limit') {
        priceGroup.style.display = 'block';
        fetchPrice(); // Fetch current price as a starting point
      } else {
        priceGroup.style.display = 'none';
      }
    });
  });
  
  // Toggle Side
  sideButtons.forEach(button => {
    button.addEventListener('click', function() {
      sideButtons.forEach(btn => btn.classList.remove('active'));
      this.classList.add('active');
      
      const side = this.getAttribute('data-value');
      sideInput.value = side;
      
      // Update submit button text and class
      submitOrderBtn.textContent = `Place ${side === 'buy' ? 'Buy' : 'Sell'} Order`;
      submitOrderBtn.className = `submit-button ${side}`;
      
      // If we have a price, update SL/TP defaults based on side
      updateStopLossTakeProfit();
    });
  });
  
  // Refresh Price Button
  refreshPriceBtn.addEventListener('click', fetchPrice);
  
  // Refresh Positions Button
  refreshPositionsBtn.addEventListener('click', loadPositions);
  
  // Calculate risk indicators when inputs change
  const riskInputs = [priceInput, stopLossInput, takeProfitInput, leverageSelect];
  riskInputs.forEach(input => {
    if (input) {
      input.addEventListener('input', calculateRiskIndicators);
    }
  });
  
  // Update Stop Loss and Take Profit based on price and side
  function updateStopLossTakeProfit() {
    const price = parseFloat(priceInput.value);
    if (!price || isNaN(price)) return;
    
    const side = sideInput.value;
    
    if (side === 'buy') {
      // For long positions: SL 2% below, TP 3% above
      stopLossInput.value = (price * 0.98).toFixed(2);
      takeProfitInput.value = (price * 1.03).toFixed(2);
    } else {
      // For short positions: SL 2% above, TP 3% below
      stopLossInput.value = (price * 1.02).toFixed(2);
      takeProfitInput.value = (price * 0.97).toFixed(2);
    }
    
    calculateRiskIndicators();
  }
  
  // Calculate Risk Indicators
  function calculateRiskIndicators() {
    const price = parseFloat(priceInput.value);
    const stopLoss = parseFloat(stopLossInput.value);
    const takeProfit = parseFloat(takeProfitInput.value);
    const side = sideInput.value;
    
    if (!price || !stopLoss || !takeProfit) return;
    
    // Calculate Risk-Reward Ratio
    let riskDistance, rewardDistance;
    
    if (side === 'buy') {
      riskDistance = price - stopLoss;
      rewardDistance = takeProfit - price;
    } else {
      riskDistance = stopLoss - price;
      rewardDistance = price - takeProfit;
    }
    
    if (riskDistance <= 0 || rewardDistance <= 0) {
      document.getElementById('risk-reward').textContent = 'Invalid';
      return;
    }
    
    const riskRewardRatio = (rewardDistance / riskDistance).toFixed(2);
    document.getElementById('risk-reward').textContent = `1:${riskRewardRatio}`;
  }
  
  // Fetch current price for a symbol
  function fetchPrice() {
    const symbol = symbolSelect.value;
    if (!symbol) return;
    
    showLoading(refreshPriceBtn);
    
    fetch(`/api/ticker/${symbol}`)
      .then(response => response.json())
      .then(data => {
        hideLoading(refreshPriceBtn);
        
        if (data.error) {
          showNotification(data.error, 'error');
          return;
        }
        
        const price = data.last;
        priceInput.value = price;
        updateStopLossTakeProfit();
      })
      .catch(error => {
        hideLoading(refreshPriceBtn);
        showNotification('Failed to fetch price', 'error');
      });
  }
  
  // Load Open Positions
  function loadPositions() {
    showLoading(refreshPositionsBtn);
    
    fetch('/api/positions')
      .then(response => response.json())
      .then(data => {
        hideLoading(refreshPositionsBtn);
        
        if (data.error) {
          showNotification(data.error, 'error');
          return;
        }
        
        if (!data.positions || data.positions.length === 0) {
          positionsContainer.innerHTML = `
            <div class="empty-positions">
              No open positions
            </div>
          `;
          return;
        }
        
        let positionsHTML = '';
        
        data.positions.forEach(position => {
          const pnlValue = parseFloat(position.unrealizedPnl) || 0;
          const pnlClass = pnlValue >= 0 ? 'profit' : (pnlValue <= -4.5 ? 'warning' : 'loss');
          const pnlPrefix = pnlValue >= 0 ? '+' : '';
          const formattedPnl = Math.abs(pnlValue).toFixed(2);
          
          // Add warning if approaching auto-liquidation
          const liquidationWarning = pnlValue <= -4.5 && pnlValue > -5 ? 
            `<div class="liquidation-warning">Approaching auto-liquidation ($${Math.abs(pnlValue).toFixed(2)}/$5.00)</div>` : '';
          
          positionsHTML += `
            <div class="position-card" data-symbol="${position.symbol}" data-side="${position.side}" data-size="${position.contracts}">
              <div class="position-header">
                <span class="position-symbol">${position.symbol}</span>
                <span class="position-side ${position.side}">${position.side.toUpperCase()}</span>
              </div>
              
              <div class="position-body">
                <div class="position-stats">
                  <div class="stat-item">
                    <span class="stat-label">Size</span>
                    <span class="stat-value">${position.contracts}</span>
                  </div>
                  
                  <div class="stat-item">
                    <span class="stat-label">Entry</span>
                    <span class="stat-value">${position.entryPrice || 'N/A'}</span>
                  </div>
                  
                  <div class="stat-item">
                    <span class="stat-label">Leverage</span>
                    <span class="stat-value">${position.leverage || 'N/A'}x</span>
                  </div>
                  
                  <div class="stat-item">
                    <span class="stat-label">PnL</span>
                    <span class="stat-value ${pnlClass}">${pnlPrefix}${formattedPnl}</span>
                  </div>
                </div>
                
                <div class="position-risk-controls">
                  <div class="row mt-2">
                    <div class="col-6">
                      <div class="stat-item">
                        <span class="stat-label">Stop Loss</span>
                        <span class="stat-value">${position.stopLoss || 'Not Set'}</span>
                      </div>
                    </div>
                    <div class="col-6">
                      <div class="stat-item">
                        <span class="stat-label">Take Profit</span>
                        <span class="stat-value">${position.takeProfit || 'Not Set'}</span>
                      </div>
                    </div>
                  </div>
                </div>
                
                ${liquidationWarning}
              </div>
              
              <div class="position-footer">
                <button type="button" class="close-position-btn">Close Position</button>
              </div>
            </div>
          `;
        });
        
        positionsContainer.innerHTML = positionsHTML;
        
        // Add event listeners to position cards
        document.querySelectorAll('.position-card').forEach(card => {
          card.addEventListener('click', function(e) {
            // Don't trigger if clicking the close button
            if (e.target.classList.contains('close-position-btn')) return;
            
            const symbol = this.getAttribute('data-symbol');
            const side = this.getAttribute('data-side');
            const size = this.getAttribute('data-size');
            
            openPositionControlModal(symbol, side, size);
          });
        });
        
        // Add event listeners to close position buttons
        document.querySelectorAll('.close-position-btn').forEach(button => {
          button.addEventListener('click', function(e) {
            e.stopPropagation(); // Prevent card click
            const card = this.closest('.position-card');
            const symbol = card.getAttribute('data-symbol');
            closePosition(symbol);
          });
        });
        
        // Start auto-liquidation check
        startAutoLiquidationCheck(data.positions);
      })
      .catch(error => {
        hideLoading(refreshPositionsBtn);
        showNotification('Failed to load positions', 'error');
      });
  }
  
  // Check for positions that need to be auto-liquidated
  function startAutoLiquidationCheck(positions) {
    // Clear any existing interval
    if (window.autoLiquidationInterval) {
      clearInterval(window.autoLiquidationInterval);
    }
    
    // Set up auto-liquidation check
    window.autoLiquidationInterval = setInterval(() => {
      fetch('/api/positions')
        .then(response => response.json())
        .then(data => {
          if (!data.positions || data.positions.length === 0) return;
          
          data.positions.forEach(position => {
            const pnlValue = parseFloat(position.unrealizedPnl) || 0;
            
            // Auto-liquidate if PnL drops below -$5
            if (pnlValue <= -5) {
              closePosition(position.symbol, true); // true = auto-liquidation
              
              showNotification(
                `Position ${position.symbol} auto-liquidated at ${Math.abs(pnlValue).toFixed(2)} loss (max $5.00)`, 
                'warning'
              );
            }
          });
        })
        .catch(error => {
          console.error('Auto-liquidation check failed:', error);
        });
    }, 5000); // Check every 5 seconds
  }
  
  // Open Position Control Modal
  function openPositionControlModal(symbol, side, size) {
    // Set modal values
    positionSymbolInput.value = symbol;
    positionSideInput.value = side;
    positionSizeInput.value = size;
    
    // Fetch current position details
    fetch(`/api/position_details/${symbol}`)
      .then(response => response.json())
      .then(data => {
        if (data.error) {
          console.error(data.error);
          return;
        }
        
        // Set stop loss and take profit values
        positionStopLossInput.value = data.stopLoss || '';
        positionTakeProfitInput.value = data.takeProfit || '';
        
        // Show the modal
        positionControlModal.show();
      })
      .catch(error => {
        console.error('Error fetching position details:', error);
        
        // Still show modal if fetch fails
        positionControlModal.show();
      });
  }
  
  // Update Position SL/TP
  updatePositionButton.addEventListener('click', function() {
    const symbol = positionSymbolInput.value;
    const side = positionSideInput.value;
    const size = positionSizeInput.value;
    const stopLoss = positionStopLossInput.value;
    const takeProfit = positionTakeProfitInput.value;
    
    if (!symbol) {
      showNotification('Symbol is required', 'error');
      return;
    }
    
    // Prepare the data
    const data = {
      symbol: symbol,
      side: side,
      quantity: parseFloat(size),
      stop_loss: stopLoss ? parseFloat(stopLoss) : null,
      take_profit: takeProfit ? parseFloat(takeProfit) : null
    };
    
    // Update the position
    fetch('/api/set_position_orders', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(result => {
      if (result.success) {
        showNotification('Position updated successfully', 'success');
        positionControlModal.hide();
        loadPositions(); // Refresh positions
      } else {
        showNotification(`Error: ${result.message}`, 'error');
      }
    })
    .catch(error => {
      showNotification('Failed to update position', 'error');
    });
  });
  
  // Close Position Button (Modal)
  closePositionButton.addEventListener('click', function() {
    const symbol = positionSymbolInput.value;
    
    if (confirm(`Are you sure you want to close position ${symbol}?`)) {
      closePosition(symbol);
      positionControlModal.hide();
    }
  });
  
  // Close a position
  function closePosition(symbol, isAutoLiquidation = false) {
    if (!symbol) return;
    
    const data = { 
      symbol: symbol,
      auto_liquidation: isAutoLiquidation 
    };
    
    fetch('/close_position', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        showNotification(
          isAutoLiquidation ? 
            `Position ${symbol} auto-liquidated (max loss reached)` : 
            `Position ${symbol} closed successfully`, 
          isAutoLiquidation ? 'warning' : 'success'
        );
        loadPositions(); // Refresh positions
      } else {
        showNotification(`Error: ${data.message}`, 'error');
      }
    })
    .catch(error => {
      showNotification('Failed to close position', 'error');
    });
  }
  
  // Check cooldown status
  function checkCooldownStatus() {
    fetch('/api/status')
      .then(response => response.json())
      .then(data => {
        if (data.cooldown_ends) {
          const cooldownEnds = new Date(data.cooldown_ends);
          const now = new Date();
          
          if (cooldownEnds > now) {
            // Cooldown is active
            cooldownEndTime = cooldownEnds;
            enableCooldownMode();
            
            // Set timer to disable cooldown mode when it ends
            const timeUntilEnd = cooldownEnds - now;
            setTimeout(disableCooldownMode, timeUntilEnd);
            
            // Update remaining time display
            startCooldownTimer();
          }
        }
      })
      .catch(error => {
        console.error('Failed to check cooldown status:', error);
      });
  }
  
  // Enable cooldown mode
  function enableCooldownMode() {
    // Disable order form
    submitOrderBtn.disabled = true;
    orderForm.classList.add('cooldown-active');
    
    // Add cooldown message
    const cooldownMessage = document.createElement('div');
    cooldownMessage.id = 'cooldown-message';
    cooldownMessage.className = 'alert alert-warning mt-3';
    cooldownMessage.innerHTML = `
      <div class="d-flex justify-content-between align-items-center">
        <span>Trading cooldown active</span>
        <span id="cooldown-timer" class="cooldown-timer"></span>
      </div>
    `;
    
    // Add to page if not already there
    if (!document.getElementById('cooldown-message')) {
      orderForm.appendChild(cooldownMessage);
    }
  }
  
  // Disable cooldown mode
  function disableCooldownMode() {
    // Enable order form
    submitOrderBtn.disabled = false;
    orderForm.classList.remove('cooldown-active');
    
    // Remove cooldown message
    const cooldownMessage = document.getElementById('cooldown-message');
    if (cooldownMessage) {
      cooldownMessage.remove();
    }
    
    // Stop cooldown timer
    if (cooldownCheckInterval) {
      clearInterval(cooldownCheckInterval);
      cooldownCheckInterval = null;
    }
  }
  
  // Start cooldown timer
  function startCooldownTimer() {
    if (cooldownCheckInterval) {
      clearInterval(cooldownCheckInterval);
    }
    
    // Update timer immediately
    updateCooldownTimer();
    
    // Then update every second
    cooldownCheckInterval = setInterval(updateCooldownTimer, 1000);
  }
  
  // Update cooldown timer display
  function updateCooldownTimer() {
    if (!cooldownEndTime) return;
    
    const now = new Date();
    const timeRemaining = cooldownEndTime - now;
    
    if (timeRemaining <= 0) {
      disableCooldownMode();
      return;
    }
    
    // Format remaining time
    const minutes = Math.floor(timeRemaining / 60000);
    const seconds = Math.floor((timeRemaining % 60000) / 1000);
    
    const timerDisplay = document.getElementById('cooldown-timer');
    if (timerDisplay) {
      timerDisplay.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
    }
  }
  
  // Form Submit
  orderForm.addEventListener('submit', function(e) {
    e.preventDefault();
    
    const formData = new FormData(this);
    const orderType = orderTypeInput.value;
    
    // Validate inputs
    const symbol = formData.get('symbol');
    const side = formData.get('side');
    const amount = parseFloat(formData.get('amount'));
    
    if (!symbol || !side || !amount) {
      showNotification('Please fill in all required fields', 'error');
      return;
    }
    
    if (orderType === 'limit' && !formData.get('price')) {
      showNotification('Price is required for limit orders', 'error');
      return;
    }
    
    // Prepare the data
    const data = {
      symbol: symbol,
      side: side,
      amount: amount,
      order_type: orderType,
      leverage: parseInt(formData.get('leverage') || 5),
      margin_mode: formData.get('margin_mode') || 'isolated'
    };
    
    // Add optional parameters
    if (orderType === 'limit') {
      data.price = parseFloat(formData.get('price'));
    }
    
    if (formData.get('stop_loss')) {
      data.stop_loss = parseFloat(formData.get('stop_loss'));
    }
    
    if (formData.get('take_profit')) {
      data.take_profit = parseFloat(formData.get('take_profit'));
    }
    
    // Disable the submit button to prevent double submissions
    submitOrderBtn.disabled = true;
    submitOrderBtn.innerHTML = '<span class="spinner"></span> Processing...';
    
    // Send the order to the server
    fetch('/place_trade', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(result => {
      // Re-enable the submit button
      submitOrderBtn.disabled = false;
      submitOrderBtn.innerHTML = `Place ${side === 'buy' ? 'Buy' : 'Sell'} Order`;
      
      if (result.success) {
        showNotification('Order placed successfully', 'success');
        loadPositions(); // Refresh positions
        
        // Check cooldown status after placing order
        checkCooldownStatus();
      } else {
        showNotification(`Error: ${result.message}`, 'error');
      }
    })
    .catch(error => {
      // Re-enable the submit button
      submitOrderBtn.disabled = false;
      submitOrderBtn.innerHTML = `Place ${side === 'buy' ? 'Buy' : 'Sell'} Order`;
      
      showNotification('Failed to place order: Network error', 'error');
    });
  });
  
  // Helper Functions
  function showLoading(element) {
    const originalContent = element.innerHTML;
    element.setAttribute('data-original-content', originalContent);
    element.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';
    element.disabled = true;
  }
  
  function hideLoading(element) {
    const originalContent = element.getAttribute('data-original-content');
    element.innerHTML = originalContent;
    element.removeAttribute('data-original-content');
    element.disabled = false;
  }
  
  function showNotification(message, type = 'success') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    
    // Add to document
    document.body.appendChild(notification);
    
    // Show notification with a slight delay for the animation
    setTimeout(() => {
      notification.classList.add('show');
    }, 10);
    
    // Hide and remove notification after 3 seconds
    setTimeout(() => {
      notification.classList.remove('show');
      
      // Remove from DOM after fade-out animation
      setTimeout(() => {
        document.body.removeChild(notification);
      }, 300);
    }, 3000);
  }
  
  // Initialize
  loadPositions();
  
  // Set up auto-refresh if needed
  const autoRefreshInterval = 30000; // 30 seconds
  setInterval(loadPositions, autoRefreshInterval);
});