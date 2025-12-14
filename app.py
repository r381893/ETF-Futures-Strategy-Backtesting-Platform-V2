# -*- coding: utf-8 -*-
"""
期貨策略回測平台 V2
簡潔、模組化、可自由組合策略
支援儲存、比較、刪除回測結果
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import yfinance as yf
import json
import os
from datetime import datetime
from config import ETF_CONFIG, FUTURES_CONFIG
from strategies import run_backtest

# =============================================================================
# 頁面設定
# =============================================================================
st.set_page_config(
    page_title="期貨策略回測 V2",
    page_icon="📈",
    layout="wide"
)

# =============================================================================
# 儲存檔案路徑
# =============================================================================
SAVED_RESULTS_FILE = "saved_backtests.json"

def load_saved_results():
    """載入已儲存的回測結果"""
    if os.path.exists(SAVED_RESULTS_FILE):
        try:
            with open(SAVED_RESULTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_results_to_file(results):
    """儲存回測結果到檔案"""
    with open(SAVED_RESULTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

# 初始化 session state
if 'saved_results' not in st.session_state:
    st.session_state.saved_results = load_saved_results()

# =============================================================================
# 主標題
# =============================================================================
st.title("📈 期貨策略回測平台 V2")

# 頁面切換
tab1, tab2, tab3 = st.tabs(["🔬 回測分析", "📊 比較已儲存", "📖 策略說明"])

# =============================================================================
# 側邊欄 - 策略設定
# =============================================================================
st.sidebar.header("⚙️ 策略設定")

# 期貨策略選擇
strategy_options = {
    'always_long': '🔵 永遠做多 (持續轉倉)',
    'ma_long': '🟢 均線波段 (>MA做多, <MA平倉)',
    'ma_trend': '🟡 均線趨勢 (>MA做多, <MA做空)',
    'etf_only': '🟤 純 ETF 持有 (不做期貨)',
}
strategy = st.sidebar.selectbox(
    "期貨策略",
    options=list(strategy_options.keys()),
    format_func=lambda x: strategy_options[x],
    index=1
)

# ETF 搭配選擇
etf_options = {
    'none': '💵 純現金 (不搭配 ETF)',
    '00631L': '🔴 00631L 台灣50正2',
    '0056': '🟠 0056 元大高股息 (歷史長)',
    '00878': '🟣 00878 國泰永續高股息',
}
etf_code = st.sidebar.selectbox(
    "搭配 ETF",
    options=list(etf_options.keys()),
    format_func=lambda x: etf_options[x],
    index=2
)

st.sidebar.markdown("---")

# 參數設定 (根據策略類型顯示)
if strategy != 'etf_only':
    # 期貨策略才需要這些參數
    ma_period = st.sidebar.slider("均線週期 (MA)", 5, 120, 13, 1)
    leverage = st.sidebar.slider("槓桿倍數", 1.0, 5.0, 2.0, 0.5)
    risk_ratio = st.sidebar.slider("保證金風險倍數", 1.0, 5.0, 3.0, 0.5)
else:
    # 純 ETF 模式不需要這些參數
    ma_period = 13  # 預設值
    leverage = 1.0
    risk_ratio = 3.0
    st.sidebar.info("📌 純 ETF 模式：不使用期貨，無需設定槓桿參數")

initial_capital = st.sidebar.number_input(
    "初始資金 (TWD)", 
    min_value=100000, 
    max_value=10000000, 
    value=1000000, 
    step=100000
)

# 進階設定與資金配置模式 (僅期貨策略需要)
if strategy != 'etf_only':
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 進階設定")
    dividend_yield = st.sidebar.slider("逆價差年化 (%)", 0.0, 10.0, 4.0, 0.5) / 100

    # 資金配置模式
    st.sidebar.markdown("---")
    st.sidebar.subheader("💰 資金配置模式")

    allocation_options = {
        'dynamic': '🔵 動態 (期貨優先，剩餘買ETF)',
        'fixed': '🟢 固定比例 (推薦)',
        'futures_only': '🟡 全期貨 (不買ETF)',
    }
    allocation_mode = st.sidebar.selectbox(
        "配置模式",
        options=list(allocation_options.keys()),
        format_func=lambda x: allocation_options[x],
        index=1
    )

    # 固定比例模式的參數
    if allocation_mode == 'fixed':
        st.sidebar.caption("設定期貨曝險與 ETF 的比例")
        futures_pct = st.sidebar.slider("期貨曝險比例 (%)", 10, 100, 60, 10) / 100
        etf_pct = st.sidebar.slider("ETF 持有比例 (%)", 0, 100, 40, 10) / 100
        
        # 顯示配置說明
        if futures_pct + etf_pct > 1:
            st.sidebar.warning("⚠️ 比例總和超過 100%，可能需要槓桿")
        else:
            remaining = 1 - futures_pct - etf_pct
            if remaining > 0:
                st.sidebar.info(f"💵 現金保留: {remaining:.0%}")
    else:
        futures_pct = 0.6
        etf_pct = 0.4
else:
    # 純 ETF 模式的預設值
    dividend_yield = 0.0
    allocation_mode = 'dynamic'
    allocation_options = {'dynamic': '動態'}  # 給後面用
    futures_pct = 0.0
    etf_pct = 1.0


# =============================================================================
# 資料載入 (含本地快取)
# =============================================================================
LOCAL_DATA_FILE = "cached_market_data.csv"

def load_from_local():
    """從本地檔案載入資料"""
    if os.path.exists(LOCAL_DATA_FILE):
        try:
            df = pd.read_csv(LOCAL_DATA_FILE, index_col=0, parse_dates=True)
            return df
        except:
            return None
    return None

def save_to_local(df):
    """儲存資料到本地檔案"""
    try:
        df.to_csv(LOCAL_DATA_FILE)
    except:
        pass

@st.cache_data(ttl=3600)
def load_data():
    """從 Yahoo Finance 下載資料，失敗時使用本地快取"""
    try:
        d_taiex = yf.download("^TWII", start="2007-01-01", progress=False, timeout=30)
        
        # 檢查是否下載成功
        if d_taiex is None or len(d_taiex) == 0:
            # 嘗試使用本地資料
            local_df = load_from_local()
            if local_df is not None:
                st.warning("⚠️ Yahoo Finance 暫時無法連線 (可能被速率限制)，使用本地快取資料")
                return local_df
            else:
                st.error("⚠️ Yahoo Finance 回傳空資料，且無本地快取")
                return None
        
        if isinstance(d_taiex.columns, pd.MultiIndex):
            d_taiex.columns = d_taiex.columns.droplevel(1)
        d_taiex = d_taiex[['Close']].rename(columns={'Close': 'TAIEX'})
        
        df = d_taiex.copy()
        
        for code, config in ETF_CONFIG.items():
            try:
                d_etf = yf.download(
                    config['yahoo_ticker'], 
                    start=config['start_date'], 
                    progress=False,
                    auto_adjust=True,
                    timeout=30
                )
                if isinstance(d_etf.columns, pd.MultiIndex):
                    d_etf.columns = d_etf.columns.droplevel(1)
                d_etf = d_etf[['Close']].rename(columns={'Close': code})
                df = pd.merge(df, d_etf, left_index=True, right_index=True, how='left')
            except Exception as etf_err:
                st.warning(f"⚠️ {code} 下載失敗: {etf_err}")
                df[code] = np.nan
        
        # 成功下載後，儲存到本地
        save_to_local(df)
        return df
        
    except Exception as e:
        # 發生錯誤時，嘗試使用本地資料
        local_df = load_from_local()
        if local_df is not None:
            st.warning(f"⚠️ Yahoo Finance 連線失敗 ({e})，使用本地快取資料")
            return local_df
        else:
            st.error(f"❌ 資料下載失敗且無本地快取: {e}")
            return None

# 清除快取按鈕
col_refresh1, col_refresh2 = st.columns([4, 1])
with col_refresh2:
    if st.button("🔄 重新載入"):
        st.cache_data.clear()
        st.rerun()

# 本地資料狀態
if os.path.exists(LOCAL_DATA_FILE):
    file_time = datetime.fromtimestamp(os.path.getmtime(LOCAL_DATA_FILE))
    col_refresh1.caption(f"📁 本地快取: {file_time.strftime('%Y-%m-%d %H:%M')}")

# 載入資料
with st.spinner("正在載入資料..."):
    df_raw = load_data()

# =============================================================================
# Tab 1: 回測分析
# =============================================================================
with tab1:
    if df_raw is not None and not df_raw.empty:
        min_date = df_raw.index.min().date()
        max_date = df_raw.index.max().date()
        
        st.sidebar.markdown("---")
        st.sidebar.subheader("📅 回測區間")
        date_range = st.sidebar.date_input(
            "選擇區間",
            value=[pd.Timestamp("2014-10-01").date(), max_date],
            min_value=min_date,
            max_value=max_date
        )
        
        if len(date_range) == 2:
            start_date, end_date = date_range
            mask = (df_raw.index >= pd.Timestamp(start_date)) & (df_raw.index <= pd.Timestamp(end_date))
            df = df_raw.loc[mask].copy()
            
            # 執行回測
            etf_dividends = ETF_CONFIG.get(etf_code, {}).get('dividends', {}) if etf_code != 'none' else {}
            
            df_result, trade_log, stats = run_backtest(
                df_data=df,
                strategy=strategy,
                etf_code=etf_code,
                etf_dividends=etf_dividends,
                initial_capital=initial_capital,
                leverage=leverage,
                ma_period=ma_period,
                risk_ratio=risk_ratio,
                dividend_yield=dividend_yield,
                allocation_mode=allocation_mode,
                futures_pct=futures_pct,
                etf_pct=etf_pct
            )
            
            # ===== 儲存按鈕 =====
            st.markdown("### 💾 儲存此回測")
            col_save1, col_save2 = st.columns([3, 1])
            
            # 自動產生名稱 (更具描述性)
            strategy_names = {
                'always_long': '永遠做多',
                'ma_long': '均線波段',
                'ma_trend': '均線趨勢',
                'etf_only': '純ETF'
            }
            etf_names = {
                'none': '純現金',
                '00631L': '00631L',
                '0056': '0056',
                '00878': '00878'
            }
            alloc_label = "固定" if allocation_mode == 'fixed' else ("動態" if allocation_mode == 'dynamic' else "純期貨")
            
            if strategy == 'etf_only':
                auto_name = f"{strategy_names[strategy]}+{etf_names[etf_code]}"
            else:
                auto_name = f"{strategy_names[strategy]}+{etf_names[etf_code]} MA{ma_period} {leverage}x ({alloc_label})"
            save_name = col_save1.text_input("回測名稱", value=auto_name)
            
            if col_save2.button("💾 儲存", type="primary"):
                # 儲存結果
                result_data = {
                    'name': save_name,
                    'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
                    'strategy': strategy,
                    'strategy_name': strategy_options[strategy],
                    'etf': etf_code,
                    'etf_name': etf_options[etf_code],
                    'ma_period': ma_period,
                    'leverage': leverage,
                    'allocation_mode': allocation_mode,
                    'allocation_name': allocation_options[allocation_mode],
                    'futures_pct': futures_pct,
                    'etf_pct': etf_pct,
                    'initial_capital': initial_capital,
                    'final_equity': stats['final_equity'],
                    'total_return': stats['total_return'],
                    'cagr': stats['cagr'],
                    'mdd': stats['mdd'],
                    'total_dividend': stats['total_dividend'],
                    'start_date': str(start_date),
                    'end_date': str(end_date),
                }
                
                # 用時間戳作為 key
                key = datetime.now().strftime('%Y%m%d_%H%M%S')
                st.session_state.saved_results[key] = result_data
                save_results_to_file(st.session_state.saved_results)
                st.success(f"✅ 已儲存: {save_name}")
            
            st.markdown("---")
            
            # 策略摘要
            st.markdown("### 📋 策略設定")
            
            if strategy == 'etf_only':
                # 純 ETF 模式：只顯示策略和 ETF 類型
                col1, col2 = st.columns(2)
                col1.info(f"**策略**: {strategy_options[strategy]}")
                col2.info(f"**搭配**: {etf_options[etf_code]}")
            else:
                # 期貨策略：顯示完整參數
                col1, col2, col3, col4 = st.columns(4)
                col1.info(f"**策略**: {strategy_options[strategy]}")
                col2.info(f"**搭配**: {etf_options[etf_code]}")
                col3.info(f"**參數**: MA{ma_period} / {leverage}x")
                
                # 配置模式顯示
                if allocation_mode == 'fixed':
                    col4.info(f"**配置**: 期貨{futures_pct:.0%} / ETF{etf_pct:.0%}")
                elif allocation_mode == 'dynamic':
                    col4.info("**配置**: 動態 (期貨優先)")
                else:
                    col4.info("**配置**: 純期貨")
            
            st.markdown("---")
            
            # 績效指標
            st.markdown("### 📊 績效摘要")
            m1, m2, m3, m4 = st.columns(4)
            
            m1.metric("💰 最終資產", f"${stats['final_equity']:,.0f}", f"{stats['total_return']:.1%}")
            m2.metric("📈 年化報酬 (CAGR)", f"{stats['cagr']:.1%}")
            m3.metric("📉 最大回撤 (MDD)", f"{stats['mdd']:.1%}")
            m4.metric("💵 累計股利", f"${stats['total_dividend']:,.0f}")
            
            st.markdown("---")
            
            # 權益曲線
            st.markdown("### 📈 權益曲線")
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_result.index, y=df_result['Equity'],
                name='策略權益', line=dict(color='#e53935', width=2)
            ))
            
            benchmark = (df_result['TAIEX'] / df_result['TAIEX'].iloc[0]) * initial_capital
            fig.add_trace(go.Scatter(
                x=df_result.index, y=benchmark,
                name='加權指數 (B&H)', line=dict(color='gray', width=1, dash='dash')
            ))
            
            if etf_code != 'none' and etf_code in df_result.columns:
                first_valid = df_result[etf_code].first_valid_index()
                if first_valid is not None:
                    etf_bh = (df_result.loc[first_valid:, etf_code] / df_result.loc[first_valid, etf_code]) * initial_capital
                    fig.add_trace(go.Scatter(
                        x=etf_bh.index, y=etf_bh,
                        name=f'{etf_code} (B&H)', line=dict(color='#1e88e5', width=1, dash='dot')
                    ))
            
            fig.update_layout(
                height=500, hovermode='x unified',
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                template="plotly_white", yaxis_title="資產淨值 (TWD)", xaxis_title="日期"
            )
            st.plotly_chart(fig, use_container_width=True)
            
            # 年度報酬
            st.markdown("---")
            st.markdown("### 📅 年度報酬")
            
            df_result['Year'] = df_result.index.year
            yearly = df_result.groupby('Year')['Equity'].agg(['first', 'last'])
            yearly['Return'] = (yearly['last'] - yearly['first']) / yearly['first']
            yearly_display = yearly[['Return']].copy()
            yearly_display.columns = ['年度報酬']
            
            def color_return(val):
                if val > 0: return 'color: red'
                elif val < 0: return 'color: green'
                return ''
            
            st.dataframe(
                yearly_display.style.format({'年度報酬': '{:.1%}'}).map(color_return),
                use_container_width=True
            )
    else:
        st.error("無法載入資料，請檢查網路連線")

# =============================================================================
# Tab 2: 比較已儲存
# =============================================================================
with tab2:
    st.markdown("### 📊 已儲存的回測結果")
    
    saved = st.session_state.saved_results
    
    if not saved:
        st.info("尚未儲存任何回測結果。請先在「回測分析」頁面進行回測並儲存。")
    else:
        # 顯示已儲存的結果列表
        data_list = []
        for key, result in saved.items():
            data_list.append({
                'key': key,
                '名稱': result.get('name', '未命名'),
                '策略': result.get('strategy_name', ''),
                'ETF': result.get('etf', ''),
                'MA': result.get('ma_period', 0),
                '槓桿': result.get('leverage', 0),
                '總報酬': result.get('total_return', 0),
                'CAGR': result.get('cagr', 0),
                'MDD': result.get('mdd', 0),
                '儲存時間': result.get('saved_at', ''),
            })
        
        df_saved = pd.DataFrame(data_list)
        
        # 選擇要比較的項目
        st.markdown("#### 選擇要比較的回測")
        
        selected_keys = []
        cols = st.columns(3)
        
        # 生成統一顯示名稱的函數
        def get_display_name(result):
            strategy_names = {
                'always_long': '永遠做多',
                'ma_long': '均線波段',
                'ma_trend': '均線趨勢',
                'etf_only': '純ETF'
            }
            strat = result.get('strategy', '')
            etf = result.get('etf', 'none')
            ma = result.get('ma_period', 13)
            lev = result.get('leverage', 1)
            alloc = result.get('allocation_mode', 'dynamic')
            alloc_label = "固定" if alloc == 'fixed' else ("動態" if alloc == 'dynamic' else "純期貨")
            
            strat_name = strategy_names.get(strat, strat)
            if strat == 'etf_only':
                return f"{strat_name}+{etf}"
            else:
                return f"{strat_name}+{etf} MA{ma} {lev}x ({alloc_label})"
        
        for i, (key, result) in enumerate(saved.items()):
            col_idx = i % 3
            with cols[col_idx]:
                display_name = get_display_name(result)
                if st.checkbox(f"**{display_name}**\n\n{result.get('cagr', 0):.1%} CAGR | {result.get('mdd', 0):.1%} MDD", key=f"check_{key}"):
                    selected_keys.append(key)
                
                # 策略說明小字
                strategy_desc = {
                    'always_long': '永遠持有期貨多單',
                    'ma_long': '價格>MA做多，<MA平倉',
                    'ma_trend': '價格>MA做多，<MA做空',
                    'etf_only': '不做期貨，純持有ETF'
                }
                alloc_desc = {
                    'dynamic': '期貨優先，剩餘買ETF',
                    'fixed': '固定比例配置',
                    'futures_only': '純期貨不買ETF'
                }
                strat = result.get('strategy', '')
                alloc = result.get('allocation_mode', 'dynamic')
                etf = result.get('etf', 'none')
                
                desc_parts = []
                if strat in strategy_desc:
                    desc_parts.append(strategy_desc[strat])
                if etf != 'none' and strat != 'etf_only':
                    desc_parts.append(f"搭配{etf}")
                if strat != 'etf_only' and alloc in alloc_desc:
                    desc_parts.append(alloc_desc[alloc])
                
                # 加入回測區間
                start_d = result.get('start_date', '')
                end_d = result.get('end_date', '')
                if start_d and end_d:
                    # 簡化日期顯示
                    start_short = start_d[:7] if len(start_d) >= 7 else start_d  # 2014-10
                    end_short = end_d[:7] if len(end_d) >= 7 else end_d
                    desc_parts.append(f"📅 {start_short} ~ {end_short}")
                
                st.caption(" | ".join(desc_parts) if desc_parts else "")
        
        st.markdown("---")
        
        # 比較表格
        if selected_keys:
            # 生成統一的顯示名稱（不依賴舊的 name 欄位）
            def generate_display_name(r):
                strategy_names = {
                    'always_long': '永遠做多',
                    'ma_long': '均線波段',
                    'ma_trend': '均線趨勢',
                    'etf_only': '純ETF'
                }
                strat = r.get('strategy', '')
                etf = r.get('etf', 'none')
                ma = r.get('ma_period', 13)
                lev = r.get('leverage', 1)
                alloc = r.get('allocation_mode', 'dynamic')
                alloc_label = "固定" if alloc == 'fixed' else ("動態" if alloc == 'dynamic' else "純期貨")
                
                strat_name = strategy_names.get(strat, strat)
                if strat == 'etf_only':
                    return f"{strat_name}+{etf}"
                else:
                    return f"{strat_name}+{etf} MA{ma} {lev}x ({alloc_label})"
            
            st.markdown("#### 📊 比較表格")
            
            compare_data = []
            for key in selected_keys:
                r = saved[key]
                compare_data.append({
                    'key': key,
                    '名稱': generate_display_name(r),
                    '策略': r.get('strategy', ''),
                    'ETF': r.get('etf', ''),
                    'MA': r.get('ma_period', 0),
                    '槓桿': f"{r.get('leverage', 0)}x",
                    '總報酬': r.get('total_return', 0),
                    'CAGR': r.get('cagr', 0),
                    'MDD': r.get('mdd', 0),
                    '初始資金': r.get('initial_capital', 0),
                    '最終資產': r.get('final_equity', 0),
                })
            
            df_compare = pd.DataFrame(compare_data)
            # 按總報酬率降序排列
            df_compare = df_compare.sort_values('總報酬', ascending=False).reset_index(drop=True)
            
            # 格式化顯示
            df_display = df_compare.copy()
            df_display['總報酬'] = df_display['總報酬'].apply(lambda x: f"{x:.1%}")
            df_display['CAGR'] = df_display['CAGR'].apply(lambda x: f"{x:.1%}")
            df_display['MDD'] = df_display['MDD'].apply(lambda x: f"{x:.1%}")
            df_display['初始資金'] = df_display['初始資金'].apply(lambda x: f"${x:,.0f}")
            df_display['最終資產'] = df_display['最終資產'].apply(lambda x: f"${x:,.0f}")
            df_display = df_display.drop(columns=['key', '策略'])
            
            st.dataframe(df_display, use_container_width=True, hide_index=True)
            
            # ===== 交易明細區塊 =====
            st.markdown("---")
            st.markdown("#### � 交易明細")
            st.caption("重新執行回測以查看每個策略的詳細交易記錄")
            
            # 選擇要查看明細的策略
            detail_options = {row['key']: row['名稱'] for _, row in df_compare.iterrows()}
            selected_detail = st.selectbox(
                "選擇策略查看交易明細",
                options=list(detail_options.keys()),
                format_func=lambda x: detail_options[x]
            )
            
            if selected_detail and st.button("🔍 執行回測查看明細", type="primary"):
                r = saved[selected_detail]
                
                # 重新執行回測獲取交易記錄
                with st.spinner("正在執行回測..."):
                    start_date = r.get('start_date', '2014-10-01')
                    end_date = r.get('end_date', str(df_raw.index.max().date()))
                    
                    mask = (df_raw.index >= pd.Timestamp(start_date)) & (df_raw.index <= pd.Timestamp(end_date))
                    df_backtest = df_raw.loc[mask].copy()
                    
                    etf_dividends = ETF_CONFIG.get(r.get('etf', 'none'), {}).get('dividends', {})
                    
                    _, trade_log, _ = run_backtest(
                        df_data=df_backtest,
                        strategy=r.get('strategy', 'ma_long'),
                        etf_code=r.get('etf', 'none'),
                        etf_dividends=etf_dividends,
                        initial_capital=r.get('initial_capital', 1000000),
                        leverage=r.get('leverage', 2.0),
                        ma_period=r.get('ma_period', 13),
                        risk_ratio=3.0,
                        dividend_yield=0.04,
                        allocation_mode=r.get('allocation_mode', 'dynamic'),
                        futures_pct=r.get('futures_pct', 0.6),
                        etf_pct=r.get('etf_pct', 0.4)
                    )
                
                if trade_log:
                    st.success(f"✅ 共 {len(trade_log)} 筆交易")
                    
                    # 顯示交易記錄
                    trade_df = pd.DataFrame(trade_log)
                    
                    # 格式化日期
                    if '日期' in trade_df.columns:
                        trade_df['日期'] = pd.to_datetime(trade_df['日期']).dt.strftime('%Y-%m-%d')
                    
                    # 計算資產變動
                    if '調整後資產' in trade_df.columns:
                        trade_df['資產變動'] = trade_df['調整後資產'].diff()
                        trade_df['資產變動'] = trade_df['資產變動'].fillna(0)
                    
                    # 樣式函數：根據類型設定背景色
                    def style_row_by_type(row):
                        if '期貨' in str(row.get('類型', '')):
                            return ['background-color: #E3F2FD'] * len(row)  # 淺藍色
                        elif 'ETF' in str(row.get('類型', '')):
                            return ['background-color: #E8F5E9'] * len(row)  # 淺綠色
                        return [''] * len(row)
                    
                    # 樣式函數：資產變動用紅綠色
                    def color_change(val):
                        if pd.isna(val) or val == 0:
                            return ''
                        elif val > 0:
                            return 'color: #D32F2F; font-weight: bold'  # 紅色（漲）
                        else:
                            return 'color: #388E3C; font-weight: bold'  # 綠色（跌）
                    
                    # 樣式函數：動作用顏色標示
                    def color_action(val):
                        if val == '做多':
                            return 'color: #D32F2F; font-weight: bold'  # 紅色
                        elif val == '平倉':
                            return 'color: #1976D2; font-weight: bold'  # 藍色
                        elif val == '做空':
                            return 'color: #388E3C; font-weight: bold'  # 綠色
                        elif val == '買入':
                            return 'color: #D32F2F'  # 紅色
                        elif val == '賣出':
                            return 'color: #388E3C'  # 綠色
                        return ''
                    
                    # 應用樣式
                    styled_df = trade_df.style.apply(style_row_by_type, axis=1)
                    
                    if '資產變動' in trade_df.columns:
                        styled_df = styled_df.map(color_change, subset=['資產變動'])
                    
                    if '動作' in trade_df.columns:
                        styled_df = styled_df.map(color_action, subset=['動作'])
                    
                    # 格式化數字
                    format_dict = {}
                    if '調整後資產' in trade_df.columns:
                        format_dict['調整後資產'] = '${:,.0f}'
                    if '資產變動' in trade_df.columns:
                        format_dict['資產變動'] = '{:+,.0f}'
                    if '交易金額' in trade_df.columns:
                        format_dict['交易金額'] = '${:,.0f}'
                    
                    if format_dict:
                        styled_df = styled_df.format(format_dict)
                    
                    st.dataframe(styled_df, use_container_width=True, hide_index=True)
                else:
                    st.info("此策略無交易記錄（可能是純 ETF 持有策略）")
            
            # 比較圖表
            st.markdown("---")
            st.markdown("#### 📈 績效比較")
            
            fig = go.Figure()
            
            # CAGR 比較 (使用排序後的順序)
            names = df_compare['名稱'].tolist()
            cagrs = [v * 100 for v in df_compare['CAGR'].tolist()]
            mdds = [abs(v) * 100 for v in df_compare['MDD'].tolist()]
            
            fig.add_trace(go.Bar(
                name='CAGR (%)', x=names, y=cagrs,
                marker_color='#4CAF50', text=[f"{v:.1f}%" for v in cagrs], textposition='outside'
            ))
            fig.add_trace(go.Bar(
                name='MDD (%)', x=names, y=mdds,
                marker_color='#f44336', text=[f"{v:.1f}%" for v in mdds], textposition='outside'
            ))
            
            fig.update_layout(
                barmode='group', height=400, template="plotly_white",
                yaxis_title="百分比 (%)", legend=dict(orientation="h", y=1.1)
            )
            st.plotly_chart(fig, use_container_width=True)
            
            # ===== 年度報酬率比較表格 =====
            st.markdown("---")
            st.markdown("#### 📅 年度報酬率比較")
            
            if st.button("📊 載入年度報酬率", type="primary"):
                with st.spinner("正在計算各策略年度報酬..."):
                    yearly_returns = {}
                    all_years = set()
                    
                    for key in selected_keys:
                        r = saved[key]
                        
                        # 重新執行回測
                        start_date = r.get('start_date', '2014-10-01')
                        end_date = r.get('end_date', str(df_raw.index.max().date()))
                        
                        mask = (df_raw.index >= pd.Timestamp(start_date)) & (df_raw.index <= pd.Timestamp(end_date))
                        df_backtest = df_raw.loc[mask].copy()
                        
                        etf_dividends = ETF_CONFIG.get(r.get('etf', 'none'), {}).get('dividends', {})
                        
                        df_result, _, _ = run_backtest(
                            df_data=df_backtest,
                            strategy=r.get('strategy', 'ma_long'),
                            etf_code=r.get('etf', 'none'),
                            etf_dividends=etf_dividends,
                            initial_capital=r.get('initial_capital', 1000000),
                            leverage=r.get('leverage', 2.0),
                            ma_period=r.get('ma_period', 13),
                            risk_ratio=3.0,
                            dividend_yield=0.04,
                            allocation_mode=r.get('allocation_mode', 'dynamic'),
                            futures_pct=r.get('futures_pct', 0.6),
                            etf_pct=r.get('etf_pct', 0.4)
                        )
                        
                        # 計算年度報酬
                        df_result['Year'] = df_result.index.year
                        yearly = df_result.groupby('Year')['Equity'].agg(['first', 'last'])
                        yearly['Return'] = (yearly['last'] - yearly['first']) / yearly['first']
                        
                        strategy_name = generate_display_name(r)
                        yearly_returns[strategy_name] = yearly['Return'].to_dict()
                        all_years.update(yearly['Return'].index.tolist())
                    
                    # 建立比較表格
                    all_years = sorted(all_years)
                    table_data = {'年度': all_years}
                    
                    for strategy_name, returns in yearly_returns.items():
                        table_data[strategy_name] = [returns.get(year, None) for year in all_years]
                    
                    df_yearly = pd.DataFrame(table_data)
                    df_yearly = df_yearly.set_index('年度')
                    
                    # 樣式函數
                    def color_yearly_return(val):
                        if pd.isna(val):
                            return 'color: gray'
                        elif val > 0:
                            return 'color: #D32F2F; font-weight: bold'  # 紅色 (漲)
                        elif val < 0:
                            return 'color: #388E3C; font-weight: bold'  # 綠色 (跌)
                        return ''
                    
                    # 格式化並顯示
                    styled_yearly = df_yearly.style.format('{:.1%}', na_rep='-').map(color_yearly_return)
                    st.dataframe(styled_yearly, use_container_width=True)
                    
                    # 平均年報酬
                    st.markdown("##### 📈 平均年報酬")
                    avg_returns = df_yearly.mean()
                    avg_df = pd.DataFrame({'策略': avg_returns.index, '平均年報酬': avg_returns.values})
                    avg_df = avg_df.sort_values('平均年報酬', ascending=False)
                    avg_df['平均年報酬'] = avg_df['平均年報酬'].apply(lambda x: f"{x:.1%}")
                    st.dataframe(avg_df, use_container_width=True, hide_index=True)
        
        # 刪除功能
        st.markdown("---")
        st.markdown("#### 🗑️ 刪除回測")
        
        # 生成帶編號和時間的刪除選項，方便區分
        delete_options = {}
        for idx, (key, result) in enumerate(saved.items(), 1):
            name = result.get('name', '未命名')
            saved_at = result.get('saved_at', '')
            cagr = result.get('cagr', 0)
            # 格式: #1 | MA13 (動態) | 30.3% CAGR | 儲存於 2025-12-13 21:27
            delete_options[key] = f"#{idx} | {name} | {cagr:.1%} CAGR | 儲存於 {saved_at}"
        
        delete_key = st.selectbox("選擇要刪除的回測", options=list(delete_options.keys()), format_func=lambda x: delete_options[x])
        
        col_del1, col_del2 = st.columns([1, 4])
        if col_del1.button("🗑️ 刪除", type="secondary"):
            if delete_key in st.session_state.saved_results:
                del st.session_state.saved_results[delete_key]
                save_results_to_file(st.session_state.saved_results)
                st.success("✅ 已刪除")
                st.rerun()

# =============================================================================
# Tab 3: 策略說明
# =============================================================================
with tab3:
    st.markdown("## 📖 策略邏輯說明")
    st.caption("本頁說明各種策略和配置模式的運作邏輯")
    
    # ===== 期貨策略 =====
    st.markdown("---")
    st.markdown("### 🎯 一、期貨策略")
    
    st.markdown("""
    期貨策略決定**何時做多、何時平倉或做空**。
    
    | 策略 | 做多條件 | 平倉/做空條件 | 風險程度 |
    |------|----------|--------------|----------|
    | 🔵 **永遠做多** | 永遠 | 永不 | ⚠️ 高 (無停損) |
    | 🟢 **均線波段** | 價格 > MA | 價格 < MA 平倉 | ✅ 中 |
    | 🟡 **均線趨勢** | 價格 > MA | 價格 < MA 做空 | ⚠️ 高 |
    | 🟤 **純 ETF 持有** | 不做期貨 | 不做期貨 | ✅ 低 |
    """)
    
    with st.expander("🔵 永遠做多 - 詳細說明", expanded=False):
        st.markdown("""
        **邏輯**：不管市場漲跌，永遠持有期貨多單。
        
        **優點**：
        - 簡單，不需判斷進出場
        - 可賺取期貨逆價差 (約 4%/年)
        
        **缺點**：
        - 大跌時沒有停損，可能大幅虧損
        - 需要足夠保證金承受波動
        
        **適合**：看好長期多頭、風險承受度高的投資人
        """)
    
    with st.expander("🟢 均線波段 - 詳細說明", expanded=False):
        st.markdown("""
        **邏輯**：
        - 價格 > 均線 → 做多
        - 價格 < 均線 → 平倉，空手等待
        
        **優點**：
        - 有停損機制，可避開大跌
        - 空手時資金安全
        
        **缺點**：
        - 盤整時可能被雙巴 (頻繁進出)
        - 會錯過急速反彈
        
        **適合**：保守型投資人，想控制風險
        """)
    
    with st.expander("🟡 均線趨勢 - 詳細說明", expanded=False):
        st.markdown("""
        **邏輯**：
        - 價格 > 均線 → 做多
        - 價格 < 均線 → 做空
        
        **優點**：
        - 多空都能賺，順勢交易
        - 趨勢明確時獲利可觀
        
        **缺點**：
        - 盤整時多空雙巴，虧損累積
        - 做空有無限風險
        
        **適合**：積極型投資人，相信趨勢
        """)
    
    with st.expander("🟤 純 ETF 持有 - 詳細說明", expanded=False):
        st.markdown("""
        **邏輯**：完全不做期貨，全部資金買入 ETF 持有。
        
        **優點**：
        - 最簡單，無需判斷進出場
        - 無期貨保證金風險
        - 可穩定領取 ETF 股利
        - 適合長期投資
        
        **缺點**：
        - 無法賺取期貨逆價差
        - 大跌時沒有避險機制
        - 報酬可能較期貨策略低
        
        **適合**：保守型投資人、想穩定領息
        """)
    
    # ===== 資金配置模式 =====
    st.markdown("---")
    st.markdown("### 💰 二、資金配置模式")
    
    st.markdown("""
    配置模式決定**資金如何分配到期貨和 ETF**。
    
    | 模式 | 期貨分配 | ETF 分配 | 特色 |
    |------|----------|----------|------|
    | 🔵 **動態** | 優先使用 | 剩餘資金 | 最大化期貨曝險 |
    | 🟢 **固定比例** | 固定 % | 固定 % | 穩定配置 |
    | 🟡 **全期貨** | 全部 | 不買 | 純期貨策略 |
    """)
    
    with st.expander("🔵 動態配置 - 運作邏輯", expanded=True):
        st.markdown("""
        **每月再平衡計算步驟：**
        
        ```
        步驟 1：計算總資產
                總資產 = 現金 + ETF 市值
        
        步驟 2：計算期貨目標
                目標曝險 = 總資產 × 槓桿倍數
                目標口數 = 目標曝險 ÷ (加權指數 × 50)
        
        步驟 3：保留保證金
                需保留 = 口數 × 85,000 × 風險倍數
        
        步驟 4：剩餘買 ETF
                可買 ETF = 總資產 - 需保留現金
        ```
        
        **範例** (總資產 100萬，2x 槓桿，風險倍數 3x)：
        
        | 項目 | 計算 | 金額 |
        |------|------|------|
        | 目標曝險 | 100萬 × 2 | 200萬 |
        | 期貨口數 | 200萬 ÷ 110萬 | ≈2 口 |
        | 需保留現金 | 2 × 85,000 × 3 | 51萬 |
        | **可買 ETF** | 100萬 - 51萬 | **49萬** |
        
        ⚠️ **注意**：ETF 金額會隨損益變動！
        """)
    
    with st.expander("🟢 固定比例 - 運作邏輯", expanded=False):
        st.markdown("""
        **設定範例**：期貨 60% / ETF 40%
        
        **每月再平衡計算：**
        
        ```
        總資產 = 100萬
        
        期貨曝險 = 100萬 × 60% × 槓桿 = 60萬 × 2x = 120萬
        ETF 持有 = 100萬 × 40% = 40萬
        ```
        
        **優點**：
        - 配置穩定，心理壓力小
        - ETF 部位不會因虧損而消失
        - 自動再平衡 (高賣低買)
        
        **適合**：想穩定領 ETF 股利的投資人
        """)
    
    with st.expander("🟡 全期貨 - 運作邏輯", expanded=False):
        st.markdown("""
        **邏輯**：不買任何 ETF，閒置資金保持現金。
        
        **適合情境**：
        - 不想承擔 ETF 價格波動風險
        - 純粹想做期貨策略
        - 需要維持高流動性
        """)
    
    # ===== ETF 說明 =====
    st.markdown("---")
    st.markdown("### 📊 三、ETF 選擇")
    
    st.markdown("""
    | ETF | 類型 | 上市時間 | 配息 | 特色 |
    |-----|------|----------|------|------|
    | 🔴 **00631L** | 槓桿型 | 2014年 | 年配 | 追蹤台灣50 2倍 |
    | 🟠 **0056** | 高股息 | 2007年 | 季配 | 歷史最長 |
    | 🟣 **00878** | 高股息 | 2020年 | 季配 | ESG 選股 |
    """)
    
    st.info("""
    💡 **建議**：
    - 想回測更長歷史 → 選 **0056** (可回測到 2007 年金融海嘯)
    - 想搭配高股息領息 → 選 **0056** 或 **00878**
    - 想槓桿加乘 → 選 **00631L** (但波動大)
    """)
    
    # ===== 參數說明 =====
    st.markdown("---")
    st.markdown("### ⚙️ 四、參數說明")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        **均線週期 (MA)**
        - 短週期 (5-13)：敏感，訊號多
        - 中週期 (20-60)：平穩，適中
        - 長週期 (60-120)：遲鈍，濾雜訊
        
        **槓桿倍數**
        - 1x：無槓桿，保守
        - 2x：常用設定
        - 3x+：高風險，謹慎使用
        """)
    
    with col2:
        st.markdown("""
        **保證金風險倍數**
        - 1x：最低保證金 (危險)
        - 3x：建議設定
        - 5x：非常保守
        
        **逆價差年化**
        - 期貨長期低於現貨約 3-5%
        - 做多可賺取這個差距
        - 保守估計用 4%
        """)

# Footer
st.markdown("---")
st.caption("📌 資料來源: Yahoo Finance | 期貨回測平台 V2")

