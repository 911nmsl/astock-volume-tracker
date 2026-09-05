import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
WECOM_WEBHOOK = os.environ["WECOM_WEBHOOK"]
BJT = timezone(timedelta(hours=8))


def fetch_history(days=400):
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/a_share_volume"
        f"?select=trade_date,volume_yi&snapshot_time=eq.15:05"
        f"&order=trade_date.desc&limit={days}",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        timeout=15
    )
    df = pd.DataFrame(resp.json())
    if df.empty:
        return df
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values('trade_date').reset_index(drop=True)
    return df


def calc_yoy_mom(df):
    latest = df.iloc[-1]
    cur_date = latest['trade_date']
    cur_vol = latest['volume_yi']

    def nearest(delta_days=None, delta_months=None, delta_years=None):
        if delta_days is not None:
            target = cur_date - pd.Timedelta(days=delta_days)
        elif delta_months is not None:
            target = cur_date - pd.DateOffset(months=delta_months)
        elif delta_years is not None:
            target = cur_date - pd.DateOffset(years=delta_years)
        else:
            return None
        mask = df['trade_date'] <= target
        if mask.sum() == 0:
            return None
        return df.loc[mask, 'volume_yi'].iloc[-1]

    def pct(base):
        return round((cur_vol - base) / base * 100, 2) if base and base > 0 else None

    return {
        "date": cur_date.strftime("%Y-%m-%d"),
        "volume_yi": cur_vol,
        "DoD": pct(nearest(delta_days=1)),
        "WoW": pct(nearest(delta_days=7)),
        "MoM": pct(nearest(delta_months=1)),
        "YoY": pct(nearest(delta_years=1)),
    }


def detect_anomaly(df, window=60, threshold=2.0):
    recent = df.tail(window)['volume_yi']
    mean_val = recent.mean()
    std_val = recent.std()
    latest_vol = df.iloc[-1]['volume_yi']
    z_score = (latest_vol - mean_val) / std_val if std_val > 0 else 0
    return {
        "z_score": round(z_score, 2),
        "mean_60d": round(mean_val, 2),
        "std_60d": round(std_val, 2),
        "is_anomaly": abs(z_score) >= threshold,
        "direction": "🔥 异常放量" if z_score >= threshold else ("🧊 异常缩量" if z_score <= -threshold else "正常")
    }


def push_wecom(title, lines):
    md = f"## {title}\n" + "\n".join(lines)
    resp = requests.post(WECOM_WEBHOOK, json={
        "msgtype": "markdown",
        "markdown": {"content": md}
    }, timeout=10)
    status = "✅" if resp.json().get("errcode") == 0 else f"❌ {resp.text}"
    print(f"微信推送: {status}")


def main():
    now = datetime.now(BJT)
    print(f"[{now.strftime('%H:%M:%S')} BJT] 生成日报...")

    df = fetch_history(400)
    if len(df) < 5:
        print("❌ 历史数据不足5条，跳过日报")
        return

    yoy = calc_yoy_mom(df)

    def arrow(val):
        if val is None:
            return "-"
        return f"**{val:+.2f}%** {'🔴' if val > 0 else '🟢'}"

    report_lines = [
        f"日期: **{yoy['date']}**",
        f"成交额: **{yoy['volume_yi']}亿**",
        f"日环比: {arrow(yoy['DoD'])}",
        f"周环比: {arrow(yoy['WoW'])}",
        f"月环比: {arrow(yoy['MoM'])}",
        f"年同比: {arrow(yoy['YoY'])}",
    ]

    anomaly = detect_anomaly(df)
    report_lines.append(f"> 60日均值: {anomaly['mean_60d']}亿 | σ: {anomaly['std_60d']}亿")

    if anomaly["is_anomaly"]:
        title = f"⚠️ A股成交额日报 ({anomaly['direction']})"
        report_lines.insert(1, f"Z-Score: **{anomaly['z_score']}** ⚠️")
    else:
        title = "📊 A股成交额日报"
        report_lines.insert(1, f"Z-Score: {anomaly['z_score']} (正常)")

    push_wecom(title, report_lines)
    print("✅ 日报生成完毕")


if __name__ == "__main__":
    main()
