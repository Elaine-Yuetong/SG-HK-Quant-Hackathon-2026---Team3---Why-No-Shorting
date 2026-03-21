# test_bot.py
from main import TradingBot
import time

bot = TradingBot()
# Run one cycle
bot.run_once()
print("Test complete")