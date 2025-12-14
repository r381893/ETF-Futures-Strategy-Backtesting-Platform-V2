# -*- coding: utf-8 -*-
"""
策略引擎模組 - 支援多種配置模式
"""
import pandas as pd
import numpy as np
from config import FUTURES_CONFIG

def run_backtest(
    df_data: pd.DataFrame,
    strategy: str,
    etf_code: str,
    etf_dividends: dict,
    initial_capital: float,
    leverage: float,
    ma_period: int,
    risk_ratio: float = 3.0,
    dividend_yield: float = 0.04,
    allocation_mode: str = 'dynamic',
    futures_pct: float = 0.6,
    etf_pct: float = 0.4
):
    """
    統一的回測引擎
    
    Args:
        df_data: 包含 TAIEX 和 ETF 價格的 DataFrame
        strategy: 策略代碼 ('always_long', 'ma_long', 'ma_trend')
        etf_code: ETF 代碼 ('none', '00631L', '0056', '00878')
        etf_dividends: ETF 股息字典
        initial_capital: 初始資金
        leverage: 槓桿倍數
        ma_period: 均線週期
        risk_ratio: 保證金風險倍數
        dividend_yield: 逆價差年化報酬
        allocation_mode: 配置模式 ('dynamic', 'fixed', 'futures_only')
        futures_pct: 固定比例模式 - 期貨曝險佔資產比例
        etf_pct: 固定比例模式 - ETF 佔資產比例
    
    Returns:
        df_result: 含權益曲線的 DataFrame
        trade_log: 交易紀錄
        stats: 績效統計
    """
    df = df_data.copy()
    
    # 計算均線
    if ma_period > 0:
        df['MA'] = df['TAIEX'].rolling(window=ma_period).mean()
    else:
        df['MA'] = np.nan
    
    # 初始化
    margin = FUTURES_CONFIG['margin_per_contract']
    point_value = FUTURES_CONFIG['point_value']
    daily_yield = dividend_yield / 252
    
    cash = initial_capital
    contracts = 0
    etf_shares = 0
    last_valid_etf_value = 0  # 追蹤最後有效的 ETF 市值
    
    equity_arr = []
    trade_log = []
    total_cost = 0
    total_dividend = 0
    
    last_month = df.index[0].month
    
    for i in range(len(df)):
        date = df.index[i]
        date_str = date.strftime('%Y-%m-%d')
        price_taiex = df['TAIEX'].iloc[i]
        price_etf = df[etf_code].iloc[i] if etf_code != 'none' and etf_code in df.columns else np.nan
        ma_val = df['MA'].iloc[i] if 'MA' in df.columns else np.nan
        
        # ===== 1. 計算 PnL =====
        if i > 0:
            prev_taiex = df['TAIEX'].iloc[i-1]
            
            # 期貨損益
            diff_pts = price_taiex - prev_taiex
            fut_pnl = contracts * diff_pts * point_value
            
            # 逆價差收益
            yield_points = prev_taiex * daily_yield
            yield_pnl = contracts * yield_points * point_value if contracts > 0 else 0
            
            cash += fut_pnl + yield_pnl
            
            # ETF 股利
            if etf_shares > 0 and date_str in etf_dividends:
                div_income = etf_shares * etf_dividends[date_str]
                cash += div_income
                total_dividend += div_income
        
        # ===== 2. 產生訊號 =====
        if strategy == 'always_long':
            signal = 1
        elif strategy == 'ma_long':
            if pd.isna(ma_val):
                signal = 0
            else:
                signal = 1 if price_taiex >= ma_val else 0
        elif strategy == 'ma_trend':
            if pd.isna(ma_val):
                signal = 0
            else:
                signal = 1 if price_taiex >= ma_val else -1
        elif strategy == 'etf_only':
            signal = 0  # 不做期貨，純 ETF
        else:
            signal = 0
        
        # ===== 3. 月初再平衡 =====
        curr_month = date.month
        rebalance = (i == 0) or (curr_month != last_month)
        
        if rebalance:
            # 計算 ETF 市值
            etf_value = etf_shares * price_etf if (etf_shares > 0 and not pd.isna(price_etf)) else 0
            total_equity = cash + etf_value
            
            # ===== 根據配置模式計算目標 =====
            
            # 特別處理: 純 ETF 策略
            if strategy == 'etf_only':
                target_contracts = 0
                required_margin = 0
                target_etf_value = total_equity if etf_code != 'none' else 0
            
            elif allocation_mode == 'dynamic':
                # 動態配置: 期貨優先，剩餘買 ETF
                target_notional = total_equity * leverage * abs(signal) if signal != 0 else 0
                target_contracts = int(round(target_notional / (price_taiex * point_value))) if price_taiex > 0 else 0
                
                if signal == -1:
                    target_contracts = -target_contracts
                elif signal == 0:
                    target_contracts = 0
                
                required_margin = abs(target_contracts) * margin * risk_ratio
                target_etf_value = max(0, total_equity - required_margin) if etf_code != 'none' else 0
                
            elif allocation_mode == 'fixed':
                # 固定比例配置
                if signal != 0:
                    # 期貨曝險 = 總資產 × 期貨比例 × 槓桿
                    target_notional = total_equity * futures_pct * leverage
                    target_contracts = int(round(target_notional / (price_taiex * point_value))) if price_taiex > 0 else 0
                    
                    if signal == -1:
                        target_contracts = -target_contracts
                    
                    # ETF = 總資產 × ETF 比例
                    target_etf_value = total_equity * etf_pct if etf_code != 'none' else 0
                else:
                    target_contracts = 0
                    target_etf_value = total_equity * etf_pct if etf_code != 'none' else 0
                
                required_margin = abs(target_contracts) * margin * risk_ratio
                
            elif allocation_mode == 'futures_only':
                # 全期貨模式: 不買 ETF
                target_notional = total_equity * leverage * abs(signal) if signal != 0 else 0
                target_contracts = int(round(target_notional / (price_taiex * point_value))) if price_taiex > 0 else 0
                
                if signal == -1:
                    target_contracts = -target_contracts
                elif signal == 0:
                    target_contracts = 0
                
                required_margin = abs(target_contracts) * margin * risk_ratio
                target_etf_value = 0  # 不買 ETF
            
            else:
                # 預設動態
                target_notional = total_equity * leverage * abs(signal) if signal != 0 else 0
                target_contracts = int(round(target_notional / (price_taiex * point_value))) if price_taiex > 0 else 0
                required_margin = abs(target_contracts) * margin * risk_ratio
                target_etf_value = max(0, total_equity - required_margin) if etf_code != 'none' else 0
            
            # ===== 執行期貨調整 =====
            diff_contracts = target_contracts - contracts
            if diff_contracts != 0:
                cost = abs(diff_contracts) * 50
                cash -= cost
                total_cost += cost
                
                # 計算當前資產 (期貨調整後)
                current_etf_value = etf_shares * price_etf if (etf_shares > 0 and not pd.isna(price_etf)) else 0
                current_equity = cash + current_etf_value
                
                # 判斷動作類型
                if target_contracts == 0:
                    action = '平倉'
                elif target_contracts > 0:
                    action = '做多' if diff_contracts > 0 else '減倉'
                else:  # target_contracts < 0
                    action = '做空'
                
                # 記錄期貨交易
                trade_log.append({
                    '日期': date_str,
                    '類型': '期貨',
                    '動作': action,
                    '口數變動': diff_contracts,
                    '調整後口數': target_contracts,
                    '指數價格': round(price_taiex, 0),
                    '手續費': cost,
                    '調整後資產': round(current_equity, 0),
                })
            contracts = target_contracts
            
            # ===== 執行 ETF 調整 =====
            if etf_code != 'none' and not pd.isna(price_etf) and price_etf > 0:
                cost_rate = 0.001  # 0.1% 手續費
                
                # 計算目標 ETF 股數
                target_etf_shares = int(target_etf_value / price_etf)
                target_etf_shares = max(0, target_etf_shares)
                
                # 計算需要買入或賣出的股數
                diff_shares = target_etf_shares - etf_shares
                
                if diff_shares > 0:
                    # 要買入：檢查是否有足夠現金
                    available_cash = max(0, cash - required_margin)
                    max_buy_shares = int(available_cash / (price_etf * (1 + cost_rate)))
                    actual_buy = min(diff_shares, max_buy_shares)
                    
                    if actual_buy > 0:
                        trade_value = actual_buy * price_etf
                        cost = trade_value * cost_rate
                        cash -= cost + trade_value
                        total_cost += cost
                        etf_shares += actual_buy
                        
                        # 計算當前資產 (ETF 買入後)
                        current_etf_value = etf_shares * price_etf
                        current_equity = cash + current_etf_value
                        
                        # 記錄 ETF 買入
                        trade_log.append({
                            '日期': date_str,
                            '類型': f'ETF ({etf_code})',
                            '動作': '買入',
                            '股數變動': actual_buy,
                            '調整後股數': etf_shares,
                            'ETF價格': round(price_etf, 2),
                            '交易金額': round(trade_value, 0),
                            '手續費': round(cost, 0),
                            '調整後資產': round(current_equity, 0),
                        })
                        
                elif diff_shares < 0:
                    # 要賣出
                    sell_shares = abs(diff_shares)
                    trade_value = sell_shares * price_etf
                    cost = trade_value * cost_rate
                    cash += trade_value - cost
                    total_cost += cost
                    etf_shares -= sell_shares
                    
                    # 計算當前資產 (ETF 賣出後)
                    current_etf_value = etf_shares * price_etf
                    current_equity = cash + current_etf_value
                    
                    # 記錄 ETF 賣出
                    trade_log.append({
                        '日期': date_str,
                        '類型': f'ETF ({etf_code})',
                        '動作': '賣出',
                        '股數變動': -sell_shares,
                        '調整後股數': etf_shares,
                        'ETF價格': round(price_etf, 2),
                        '交易金額': round(trade_value, 0),
                        '手續費': round(cost, 0),
                        '調整後資產': round(current_equity, 0),
                    })
            
            last_month = curr_month
        
        # ===== 4. 計算當日權益 =====
        # 處理 NaN 價格：使用上一個有效價格
        if etf_shares > 0:
            if not pd.isna(price_etf) and price_etf > 0:
                etf_value = etf_shares * price_etf
                last_valid_etf_value = etf_value  # 記錄有效值
            else:
                # 價格是 NaN，使用上次的市值
                etf_value = last_valid_etf_value
        else:
            etf_value = 0
            
        total_equity = cash + etf_value
        
        # 防止權益變成負數或零
        if total_equity <= 0:
            total_equity = equity_arr[-1] if equity_arr else initial_capital
            
        equity_arr.append(total_equity)
    
    # 結果
    df['Equity'] = equity_arr
    
    # 績效統計
    final_equity = equity_arr[-1] if equity_arr else initial_capital
    total_return = (final_equity - initial_capital) / initial_capital
    
    days = (df.index[-1] - df.index[0]).days
    years = max(days / 365.25, 0.01)
    cagr = (final_equity / initial_capital) ** (1 / years) - 1
    
    # MDD
    equity_series = pd.Series(equity_arr, index=df.index)
    roll_max = equity_series.cummax()
    drawdown = (equity_series - roll_max) / roll_max
    mdd = drawdown.min()
    
    stats = {
        'initial_capital': initial_capital,
        'final_equity': final_equity,
        'total_return': total_return,
        'cagr': cagr,
        'mdd': mdd,
        'total_cost': total_cost,
        'total_dividend': total_dividend,
        'allocation_mode': allocation_mode,
        'futures_pct': futures_pct,
        'etf_pct': etf_pct,
    }
    
    return df, trade_log, stats
