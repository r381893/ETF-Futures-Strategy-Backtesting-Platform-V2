# -*- coding: utf-8 -*-
import pandas as pd
import yfinance as yf

# 下載 00631L 資料
df = yf.download('00631L.TW', start='2014-10-01', progress=False, auto_adjust=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.droplevel(1)

print('=== 00631L 原始價格 (auto_adjust=False) ===')
print('起始日期:', df.index[0].strftime('%Y-%m-%d'))
print('起始價格:', round(float(df['Close'].iloc[0]), 2))
print('結束日期:', df.index[-1].strftime('%Y-%m-%d'))
print('結束價格:', round(float(df['Close'].iloc[-1]), 2))
total_return = (float(df['Close'].iloc[-1]) - float(df['Close'].iloc[0])) / float(df['Close'].iloc[0]) * 100
print('純價差報酬:', round(total_return, 1), '%')

# 對比 auto_adjust=True
df2 = yf.download('00631L.TW', start='2014-10-01', progress=False, auto_adjust=True)
if isinstance(df2.columns, pd.MultiIndex):
    df2.columns = df2.columns.droplevel(1)
    
print()
print('=== 00631L 調整價格 (auto_adjust=True) ===')
print('起始價格:', round(float(df2['Close'].iloc[0]), 2))
print('結束價格:', round(float(df2['Close'].iloc[-1]), 2))
total_return2 = (float(df2['Close'].iloc[-1]) - float(df2['Close'].iloc[0])) / float(df2['Close'].iloc[0]) * 100
print('含股利調整報酬:', round(total_return2, 1), '%')
