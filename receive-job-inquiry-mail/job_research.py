"""
job_research.py - 求人媒体週次リサーチモジュール

Indeed Japan の公開 RSS フィードを使って競合求人情報を取得・分析する。
API 登録不要・scraping 不要・Indeed の公式 RSS 仕様に準拠。

【動作の流れ】
  Indeed RSS → 求人一覧取得 → 件数/給与/企業を分析 → ChatWork レポート生成

【検索対象カテゴリ】
  - IT・システム開発（SES・ITエンジニア）
  - プロジェクトマネージャー
  - インフラ・ネットワークエンジニア
  - 営業（IT/SaaS）
"""

import logging
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import defusedxml.ElementTree as ET  # XXE 攻撃を防ぐ安全な XML パーサー
from defusedxml import DefusedXmlException
import httpx

logger = logging.getLogger(__name__)

# =============================================================================
# 検索クエリ定義（soulsyncs が対象とする職種）
# =============================================================================

SEARCH_QUERIES = [
    {
        "label": "SES・ITエンジニア派遣",
        "q": "SES ITエンジニア 派遣",
        "l": "東京都",
    },
    {
        "label": "システム開発エンジニア",
        "q": "システム開発 プログラマー 正社員",
        "l": "東京都",
    },
    {
        "label": "インフラ・ネットワークエンジニア",
        "q": "インフラエンジニア ネットワーク 派遣",
        "l": "東京都",
    },
    {
        "label": "ITプロジェクトマネージャー",
        "q": "プロジェクトマネージャー IT PM 派遣",
        "l": "東京都",
    },
]

# Indeed Japan RSS のベース URL
_INDEED_RSS_BASE = "https://www.indeed.co.jp/rss"

# Indeed 独自 XML 名前空間（仕様変更に備えてフォールバック付きで使用）
_NS = "https://www.indeed.com/about/rss"


def _find_ns(item: ET.Element, tag: str) -> Optional[ET.Element]:
    """
    名前空間付きタグを検索し、見つからない場合はフォールバックで
    名前空間なしのタグも検索する（Indeed RSS の仕様変更に対応）。
    """
    result = item.find(f"{{{_NS}}}{tag}")
    if result is None:
        result = item.find(tag)
    return result

# 1回のリクエストで取得する最大件数
_MAX_RESULTS_PER_QUERY = 25


# =============================================================================
# データ構造
# =============================================================================

@dataclass
class JobPosting:
    """1件の求人情報"""
    title: str
    company: str
    location: str
    salary: Optional[str] = None
    url: str = ""


@dataclass
class ResearchResult:
    """1カテゴリ分のリサーチ結果"""
    label: str
    query: str
    total_count: int
    sample_postings: List[JobPosting] = field(default_factory=list)
    salary_count: int = 0
    top_companies: List[str] = field(default_factory=list)


# =============================================================================
# Indeed RSS 取得
# =============================================================================

def _fetch_indeed_rss(query: str, location: str, limit: int = _MAX_RESULTS_PER_QUERY) -> List[JobPosting]:
    """
    Indeed Japan の RSS フィードから求人情報を取得する。
    取得失敗時は空リストを返す（例外は上位に伝播させない）。
    """
    params = {
        "q": query,
        "l": location,
        "limit": str(limit),
        "sort": "date",
    }
    url = _INDEED_RSS_BASE + "?" + urllib.parse.urlencode(params)

    try:
        with httpx.Client(
            timeout=15.0,
            headers={"User-Agent": "Mozilla/5.0 (compatible; job-research-bot/1.0)"},
            follow_redirects=True,
        ) as client:
            resp = client.get(url)

        if resp.status_code != 200:
            logger.warning(f"Indeed RSS 取得失敗 (status={resp.status_code}): {query}")
            return []

        # resp.content（bytes）を渡すことで XML 宣言の encoding 指定と競合しない
        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            logger.warning(f"Indeed RSS: channel タグが見つかりません: {query}")
            return []

        postings: List[JobPosting] = []
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            if not title:
                continue

            # Indeed 独自名前空間タグ（名前空間変更に対応したフォールバック付き）
            company_tag = _find_ns(item, "company")
            company = (company_tag.text or "").strip() if company_tag is not None else ""

            city_tag = _find_ns(item, "city")
            state_tag = _find_ns(item, "state")
            location_parts = []
            if state_tag is not None and state_tag.text:
                location_parts.append(state_tag.text.strip())
            if city_tag is not None and city_tag.text:
                location_parts.append(city_tag.text.strip())
            loc = " ".join(location_parts) if location_parts else location

            salary_tag = _find_ns(item, "salary")
            salary = (salary_tag.text or "").strip() if salary_tag is not None else None
            if not salary:
                salary = None

            link = (item.findtext("link") or "").strip()

            postings.append(JobPosting(
                title=title,
                company=company,
                location=loc,
                salary=salary,
                url=link,
            ))

        return postings

    except (ET.ParseError, DefusedXmlException) as e:
        logger.warning(f"Indeed RSS 解析エラー: {e} (query={query})")
        return []
    except Exception as e:
        logger.error(f"Indeed RSS 取得例外: {e} (query={query})")
        return []


# =============================================================================
# 分析
# =============================================================================

def _analyze(label: str, query: str, postings: List[JobPosting]) -> ResearchResult:
    """取得した求人一覧を分析してサマリーを作る"""

    # 給与記載件数
    salary_count = sum(1 for p in postings if p.salary)

    # 上位企業（出現回数が多い順）
    company_counts: dict[str, int] = {}
    for p in postings:
        if p.company:
            company_counts[p.company] = company_counts.get(p.company, 0) + 1
    top_companies = sorted(company_counts, key=lambda c: -company_counts[c])[:5]

    return ResearchResult(
        label=label,
        query=query,
        total_count=len(postings),
        sample_postings=postings[:5],
        salary_count=salary_count,
        top_companies=top_companies,
    )


# =============================================================================
# ChatWork メッセージ生成
# =============================================================================

def _build_chatwork_message(results: List[ResearchResult]) -> str:
    """リサーチ結果を ChatWork 投稿用テキストに変換する"""
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).strftime("%Y年%m月%d日")

    lines = [
        f"📊【週次求人媒体リサーチ】{today}",
        "Indeed Japan の直近求人状況をお届けします（毎週月曜更新）",
        "=" * 36,
    ]

    for r in results:
        lines.append(f"\n■ {r.label}")
        lines.append(f"  求人件数: {r.total_count}件（直近/東京都）")

        if r.total_count > 0:
            salary_pct = int(r.salary_count / r.total_count * 100)
            lines.append(f"  給与記載あり: {r.salary_count}件（{salary_pct}%）")

        if r.top_companies:
            companies_str = "、".join(r.top_companies[:3])
            lines.append(f"  掲載企業（上位）: {companies_str}")

        if r.sample_postings:
            lines.append("  【直近の求人タイトル例】")
            for p in r.sample_postings[:3]:
                salary_str = f" [{p.salary}]" if p.salary else ""
                lines.append(f"  ・{p.title}{salary_str}")

    lines += [
        "",
        "=" * 36,
        "※ Indeed Japan 公開RSS（最新順・東京都）より自動取得",
        "※ 競合状況の参考としてご活用ください",
    ]

    return "\n".join(lines)


# =============================================================================
# 公開 API
# =============================================================================

def run_weekly_research() -> Optional[str]:
    """
    週次リサーチを実行して ChatWork 投稿用メッセージを返す。

    取得に完全失敗した場合のみ None を返す。
    一部カテゴリの失敗は無視して残りのデータで報告する。

    Returns:
        str: ChatWork 投稿用テキスト
        None: データを1件も取得できなかった場合
    """
    results: List[ResearchResult] = []

    for q in SEARCH_QUERIES:
        postings = _fetch_indeed_rss(q["q"], q["l"])
        if postings:
            r = _analyze(q["label"], q["q"], postings)
            results.append(r)
            logger.info(f"リサーチ完了: {q['label']} → {len(postings)}件")
        else:
            logger.warning(f"データなし: {q['label']}")

    if not results:
        logger.error("Indeed RSS から求人情報を1件も取得できませんでした")
        return None

    return _build_chatwork_message(results)
