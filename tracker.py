import os
import requests
import akshare as ak
import numpy as np
from datetime import datetime, timezone, timedelta

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
WECOM_WEBHOOK = os.environ["WECOM_WEBHOOK"]
BJT = timezone(timedelta(hours=8))


def main():
    now = datetime.now(BJT)
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    print(f"[{now.strftime('%H:%M:%S')} BJT] 开始采集...")

    # 1. 采集沪深成交额
    df_sh_sz = ak.stock_zh_a_spot_em()
    sh_sz_yi = round(df_sh_sz['成交额'].sum() / 1e8, 2)

    # 2. 采集北交所成交额
    try:
        df_bj = ak.stock_bj_a_spot_em()
        bj_yi = round(df_bj['成交额'].sum() / 1e8, 2)
    except Exception as e:
        print(f"北交所采集失败: {e}")
        bj_yi = 0

    total_yi = round(sh_sz_yi + bj_yi, 2)
    print(f"三市成交额: {total_yi}亿 (沪深:{sh_sz_yi} | 北交:{bj_yi})")

    # 3. 写入 Supabase
    record = {
        "trade_date": today_str,
        "snapshot_time": time_str,
        "volume_yi": total_yi,
        "sh_sz_yi": sh_sz_yi,
        "bj_yi": bj_yi
    }
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/a_share_volume",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
        },
        json=[record],
        timeout=15
    )
    print(f"Supabase: {'✅' if resp.status_code in (200,201) else '❌ ' + str(resp.status_code)}")

    # ===== 盘中异常检测 =====
    try:
        hist_resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/a_share_volume"
            f"?select=volume_yi&snapshot_time=eq.{time_str}"
            f"&order=trade_date.desc&limit=60",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
            timeout=10
        )
        hist_vols = [r['volume_yi'] for r in hist_resp.json()]
        if len(hist_vols) >= 20:
            mean_v = np.mean(hist_vols)
            std_v = np.std(hist_vols)
            z = (total_yi - mean_v) / std_v if std_v > 0 else 0
            if abs(z) >= 2.0:
                direction = "🔥 异常放量" if z > 0 else "🧊 异常缩量"
                alert_md = (
                    f"## ⚠️ 盘中异常告警 ({direction})\n"
                    f"时间: **{today_str} {time_str}**\n"
                    f"当前成交: **{total_yi}亿** | Z-Score: **{z:.2f}**\n"
                    f"同时段60日均值: {mean_v:.0f}亿 | σ: {std_v:.0f}亿\n"
                    f"> ⏱ {now.strftime('%H:%M:%S')} 实时告警"
                )
                requests.post(WECOM_WEBHOOK, json={
                    "msgtype": "markdown",
                    "markdown": {"content": alert_md}
                }, timeout=10)
                print(f"⚠️ 异常告警已推送 (Z={z:.2f})")
            else:
                print(f"异常检测正常 (Z={z:.2f})")
        else:
            print(f"历史数据不足({len(hist_vols)}条)，跳过异常检测")
    except Exception as e:
        print(f"异常检测跳过: {e}")
    # ===== 异常检测结束 =====

    # 4. 推送常规消息到企业微信
    emoji = "🔴" if total_yi > 8000 else "🟢"
    md = (
        f"## 📊 A股三市成交额 ({time_str})\n"
        f"日期: **{today_str}**\n"
        f"三市合计: **{total_yi}亿** {emoji}\n"
        f"沪深: {sh_sz_yi}亿 | 北交: {bj_yi}亿\n"
        f"> ⏱ {now.strftime('%H:%M:%S')} 云端快照"
    )
    wr = requests.post(WECOM_WEBHOOK, json={
        "msgtype": "markdown",
        "markdown": {"content": md}
    }, timeout=10)
    print(f"微信推送: {'✅' if wr.json().get('errcode') == 0 else '❌'}")


if __name__ == "__main__":
    main()
