import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="A股成交额监控", page_icon="📊", layout="wide")
st.title("📊 A股三市成交额实时监控看板")

SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("❌ 未配置 Supabase 密钥，请在 Streamlit Secrets 中添加 SUPABASE_URL 和 SUPABASE_KEY")
    st.stop()


@st.cache_data(ttl=300)
def load_data():
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/a_share_volume?select=*&order=trade_date.asc",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        timeout=15
    )
    df = pd.DataFrame(resp.json())
    if df.empty:
        return df
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df['datetime'] = pd.to_datetime(df['trade_date'].dt.strftime('%Y-%m-%d') + ' ' + df['snapshot_time'])
    return df


df = load_data()

if df.empty:
    st.warning("暂无数据，请等待采集脚本运行后刷新页面")
    st.stop()

# KPI 卡片
close_df = df[df['snapshot_time'] == '15:05'].copy()
latest = close_df.iloc[-1] if not close_df.empty else None

if latest is not None:
    col1, col2, col3, col4 = st.columns(4)
    prev = close_df.iloc[-2] if len(close_df) >= 2 else None
    dod = ((latest['volume_yi'] - prev['volume_yi']) / prev['volume_yi'] * 100) if prev is not None else 0

    col1.metric("最新收盘成交额", f"{latest['volume_yi']:,.0f}亿", f"{dod:+.1f}%")
    col2.metric("沪深", f"{latest['sh_sz_yi']:,.0f}亿")
    col3.metric("北交所", f"{latest['bj_yi']:,.0f}亿")

    if len(close_df) >= 60:
        ma60 = close_df.tail(60)['volume_yi'].mean()
        col4.metric("60日均值", f"{ma60:,.0f}亿", f"{((latest['volume_yi']-ma60)/ma60*100):+.1f}%")
    else:
        col4.metric("60日均值", "数据积累中")

st.divider()

# 分时趋势图
st.subheader("📈 日内分时成交额趋势")
time_options = sorted(df['snapshot_time'].unique())
selected_times = st.multiselect("选择时间点", time_options, default=time_options)
mask = df['snapshot_time'].isin(selected_times)
fig1 = px.line(df[mask], x='trade_date', y='volume_yi', color='snapshot_time',
               markers=True, title="各时间点成交额走势")
fig1.update_layout(height=400)
st.plotly_chart(fig1, use_container_width=True)

# 收盘成交额+均线
st.subheader("📉 收盘成交额 & 移动均线")
if not close_df.empty:
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(x=close_df['trade_date'], y=close_df['volume_yi'],
                          name='成交额', marker_color='#3498db', opacity=0.7))
    for window, color in [(20, '#e74c3c'), (60, '#f39c12')]:
        if len(close_df) >= window:
            ma = close_df['volume_yi'].rolling(window).mean()
            fig2.add_trace(go.Scatter(x=close_df['trade_date'], y=ma,
                                      name=f'MA{window}', line=dict(color=color, width=2)))
    fig2.update_layout(height=400, title="收盘成交额与均线")
    st.plotly_chart(fig2, use_container_width=True)

# Z-Score 异常监测
st.subheader("🔍 成交额异常监测 (Z-Score)")
if len(close_df) >= 60:
    rolling_mean = close_df['volume_yi'].rolling(60).mean()
    rolling_std = close_df['volume_yi'].rolling(60).std()
    close_df_copy = close_df.copy()
    close_df_copy['z_score'] = (close_df_copy['volume_yi'] - rolling_mean) / rolling_std
    valid = close_df_copy.dropna(subset=['z_score']).tail(120)

    colors = ['#27ae60' if abs(z) < 2 else ('#e74c3c' if z > 0 else '#2980b9') for z in valid['z_score']]
    fig3 = go.Figure(go.Bar(x=valid['trade_date'], y=valid['z_score'], marker_color=colors))
    fig3.add_hline(y=2, line_dash="dash", line_color="red", annotation_text="+2σ")
    fig3.add_hline(y=-2, line_dash="dash", line_color="blue", annotation_text="-2σ")
    fig3.update_layout(height=350, title="Z-Score 分布 (红=放量异常 / 蓝=缩量异常 / 绿=正常)")
    st.plotly_chart(fig3, use_container_width=True)
else:
    st.info("需积累至少60个交易日收盘数据后显示异常监测图")

# 原始数据
with st.expander("📋 查看原始数据"):
    st.dataframe(df.sort_values('datetime', ascending=False).head(100), use_container_width=True)
