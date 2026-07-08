#!/usr/bin/env python3
"""Generate Wanhelp GA4 weekly report (App + Web). No MCP required."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.request
from datetime import date, timedelta
from pathlib import Path

APP_PROPERTY = os.environ.get("GA4_APP_PROPERTY_ID", "485160402")
WEB_PROPERTY = os.environ.get("GA4_WEB_PROPERTY_ID", "502598309")
SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
REPORT_DIR = Path(__file__).resolve().parents[1] / "memory"


def resolve_credentials_path() -> str:
    inline = os.environ.get("GA4_SERVICE_ACCOUNT_JSON")
    if inline:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(inline)
        tmp.close()
        return tmp.name
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if path and Path(path).is_file():
        return path
    default = Path.home() / ".secrets/wanhelp/ga4-service-account.json"
    if default.is_file():
        return str(default)
    raise SystemExit(
        "Missing credentials: set GOOGLE_APPLICATION_CREDENTIALS or GA4_SERVICE_ACCOUNT_JSON"
    )


def get_token(creds_path: str) -> str:
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request

    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=[SCOPE])
    creds.refresh(Request())
    return creds.token


def run_report(token: str, property_id: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def metric_row(report: dict) -> list[str]:
    if not report.get("rows"):
        return ["0", "0", "0", "0"]
    return [v["value"] for v in report["rows"][0]["metricValues"]]


def fmt_duration(seconds: str) -> str:
    sec = int(float(seconds))
    m, s = divmod(sec, 60)
    return f"{m}m {s:02d}s"


def pct(cur: str, prev: str) -> str:
    if not prev or float(prev) == 0:
        return "N/A"
    return f"{(float(cur) - float(prev)) / float(prev) * 100:+.1f}%"


def query_summary(token: str, property_id: str, start: str, end: str) -> dict:
    body = {
        "dateRanges": [{"startDate": start, "endDate": end}],
        "metrics": [
            {"name": "activeUsers"},
            {"name": "newUsers"},
            {"name": "sessions"},
            {"name": "averageSessionDuration"},
        ],
    }
    r = run_report(token, property_id, body)
    au, nu, ss, dur = metric_row(r)
    return {"activeUsers": au, "newUsers": nu, "sessions": ss, "duration": fmt_duration(dur)}


def main() -> None:
    creds_path = resolve_credentials_path()
    token = get_token(creds_path)

    last7 = {"startDate": "7daysAgo", "endDate": "today"}
    prev7 = {"startDate": "14daysAgo", "endDate": "8daysAgo"}

    app_last = query_summary(token, APP_PROPERTY, last7["startDate"], last7["endDate"])
    app_prev = query_summary(token, APP_PROPERTY, prev7["startDate"], prev7["endDate"])
    web_last = query_summary(token, WEB_PROPERTY, last7["startDate"], last7["endDate"])
    web_prev = query_summary(token, WEB_PROPERTY, prev7["startDate"], prev7["endDate"])

    platform = run_report(
        token,
        APP_PROPERTY,
        {
            "dateRanges": [last7],
            "dimensions": [{"name": "platform"}],
            "metrics": [{"name": "activeUsers"}, {"name": "newUsers"}],
        },
    )

    monday = date.today() - timedelta(days=date.today().weekday())
    out = REPORT_DIR / f"ga4-weekly-{monday.isoformat()}.md"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# GA4 增长周报 · {monday.isoformat()}",
        "",
        f"> App Property: `{APP_PROPERTY}` | Web Property: `{WEB_PROPERTY}`",
        "> 由 `.workbuddy/scripts/ga4_weekly_report.py` 自动生成",
        "",
        "## App 大盘",
        "",
        "| 指标 | 近7日 | 再前7日 | 环比 |",
        "|------|------|--------|------|",
        f"| 活跃用户 | {app_last['activeUsers']} | {app_prev['activeUsers']} | {pct(app_last['activeUsers'], app_prev['activeUsers'])} |",
        f"| 新用户 | {app_last['newUsers']} | {app_prev['newUsers']} | {pct(app_last['newUsers'], app_prev['newUsers'])} |",
        f"| 会话数 | {app_last['sessions']} | {app_prev['sessions']} | {pct(app_last['sessions'], app_prev['sessions'])} |",
        f"| 平均会话时长 | {app_last['duration']} | {app_prev['duration']} | — |",
        "",
        "## Web wanhelp.com",
        "",
        "| 指标 | 近7日 | 再前7日 | 环比 |",
        "|------|------|--------|------|",
        f"| 活跃用户 | {web_last['activeUsers']} | {web_prev['activeUsers']} | {pct(web_last['activeUsers'], web_prev['activeUsers'])} |",
        f"| 新用户 | {web_last['newUsers']} | {web_prev['newUsers']} | {pct(web_last['newUsers'], web_prev['newUsers'])} |",
        f"| 会话数 | {web_last['sessions']} | {web_prev['sessions']} | {pct(web_last['sessions'], web_prev['sessions'])} |",
        f"| 平均会话时长 | {web_last['duration']} | {web_prev['duration']} | — |",
        "",
        "## App 平台拆分（近7日）",
        "",
        "| 平台 | 活跃用户 | 新用户 |",
        "|------|---------|--------|",
    ]
    for row in platform.get("rows", []):
        p = row["dimensionValues"][0]["value"]
        au = row["metricValues"][0]["value"]
        nu = row["metricValues"][1]["value"]
        lines.append(f"| {p} | {au} | {nu} |")

    lines.extend(
        [
            "",
            "## 双轨提醒",
            "",
            "- 注册漏斗 / 渠道 CPA / AI 质量 → **神策**",
            "- 大盘活跃 / 网站流量 → **GA4**",
            "",
        ]
    )

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
