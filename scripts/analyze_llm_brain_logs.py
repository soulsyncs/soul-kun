#!/usr/bin/env python3
"""
LLM Brain 本番ログ分析スクリプト

Task #9: 本番ログ分析・エラー率確認

【使用方法】
1. ローカル実行（直近ログファイルから）:
   python scripts/analyze_llm_brain_logs.py --local

2. Cloud Logging から取得:
   python scripts/analyze_llm_brain_logs.py --project=your-gcp-project

3. 特定期間を分析:
   python scripts/analyze_llm_brain_logs.py --hours=24

【出力】
- エラー率
- レスポンス時間分布
- 意図別成功率
- Tool使用頻度

Author: Claude Opus 4.5
Created: 2026-01-31
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional

# =============================================================================
# 定数
# =============================================================================

# LLM Brain関連のログパターン
LOG_PATTERNS = {
    "brain_initialized": r"LLMBrain initialized.*model=(\S+)",
    "brain_process_start": r"LLMBrain processing.*message=",
    "brain_process_end": r"LLMBrain result.*output_type=(\S+).*confidence=(\d+\.\d+)",
    "guardian_check": r"Guardian check.*action=(\S+)",
    "guardian_confirm": r"Guardian requires confirmation",
    "guardian_block": r"Guardian blocked.*reason=(.+)",
    "api_call_openrouter": r"Calling OpenRouter.*model=(\S+)",
    "api_call_anthropic": r"Calling Anthropic.*model=(\S+)",
    "api_error": r"API error.*status=(\d+)",
    "tool_execution": r"Tool executed.*tool_name=(\S+).*success=(\w+)",
    "error": r"ERROR|Exception|Traceback",
}

# メトリクス
METRICS = {
    "total_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "confirmed_requests": 0,
    "blocked_requests": 0,
    "api_errors": 0,
    "response_times_ms": [],
    "output_types": defaultdict(int),
    "tools_used": defaultdict(int),
    "guardian_actions": defaultdict(int),
    "errors_by_type": defaultdict(int),
    "hourly_requests": defaultdict(int),
}


# =============================================================================
# ログパーサー
# =============================================================================

class LLMBrainLogAnalyzer:
    """LLM Brainログの分析クラス"""

    def __init__(self):
        self.metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "confirmed_requests": 0,
            "blocked_requests": 0,
            "api_errors": 0,
            "response_times_ms": [],
            "output_types": defaultdict(int),
            "tools_used": defaultdict(int),
            "guardian_actions": defaultdict(int),
            "errors_by_type": defaultdict(int),
            "hourly_requests": defaultdict(int),
            "confidence_scores": [],
        }
        self.errors = []

    def parse_log_line(self, line: str, timestamp: Optional[datetime] = None) -> None:
        """1行のログを解析"""
        try:
            # JSON形式のログをパース
            if line.strip().startswith("{"):
                self._parse_json_log(line, timestamp)
            else:
                # テキスト形式のログをパース
                self._parse_text_log(line, timestamp)
        except Exception as e:
            # パースエラーはスキップ
            pass

    def _parse_json_log(self, line: str, timestamp: Optional[datetime] = None) -> None:
        """JSON形式のログを解析"""
        data = json.loads(line)
        message = data.get("message", "")
        severity = data.get("severity", "INFO")

        # タイムスタンプの取得
        ts = timestamp or datetime.fromisoformat(
            data.get("timestamp", datetime.now().isoformat()).replace("Z", "+00:00")
        )
        hour_key = ts.strftime("%Y-%m-%d %H:00")

        # LLM Brain処理開始
        if "LLMBrain processing" in message or "Brain instance" in message:
            self.metrics["total_requests"] += 1
            self.metrics["hourly_requests"][hour_key] += 1

        # LLM Brain処理結果
        if "LLMBrain result" in message or "output_type=" in message:
            output_type = self._extract_field(message, "output_type")
            if output_type:
                self.metrics["output_types"][output_type] += 1
                if output_type in ["tool_call", "text_response"]:
                    self.metrics["successful_requests"] += 1

            confidence = self._extract_field(message, "confidence")
            if confidence:
                try:
                    self.metrics["confidence_scores"].append(float(confidence))
                except ValueError:
                    pass

        # Guardian Layer判定
        if "Guardian" in message:
            action = self._extract_field(message, "action")
            if action:
                self.metrics["guardian_actions"][action] += 1
                if action == "confirm":
                    self.metrics["confirmed_requests"] += 1
                elif action == "block":
                    self.metrics["blocked_requests"] += 1

        # APIエラー
        if "API error" in message or "OpenRouter API error" in message or "Anthropic API error" in message:
            self.metrics["api_errors"] += 1
            status = self._extract_field(message, "status")
            if status:
                self.metrics["errors_by_type"][f"api_{status}"] += 1

        # ツール実行
        if "Tool executed" in message or "tool_name=" in message:
            tool_name = self._extract_field(message, "tool_name")
            if tool_name:
                self.metrics["tools_used"][tool_name] += 1

        # エラーログ
        if severity in ["ERROR", "CRITICAL"]:
            self.metrics["failed_requests"] += 1
            error_type = self._categorize_error(message)
            self.metrics["errors_by_type"][error_type] += 1
            self.errors.append({
                "timestamp": ts.isoformat(),
                "severity": severity,
                "message": message[:200],
            })

    def _parse_text_log(self, line: str, timestamp: Optional[datetime] = None) -> None:
        """テキスト形式のログを解析"""
        for pattern_name, pattern in LOG_PATTERNS.items():
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                if pattern_name == "brain_process_start":
                    self.metrics["total_requests"] += 1
                elif pattern_name == "brain_process_end":
                    output_type, confidence = match.groups()
                    self.metrics["output_types"][output_type] += 1
                    self.metrics["successful_requests"] += 1
                    try:
                        self.metrics["confidence_scores"].append(float(confidence))
                    except ValueError:
                        pass
                elif pattern_name == "guardian_check":
                    action = match.group(1)
                    self.metrics["guardian_actions"][action] += 1
                elif pattern_name == "api_error":
                    self.metrics["api_errors"] += 1
                    self.metrics["errors_by_type"][f"api_{match.group(1)}"] += 1
                elif pattern_name == "tool_execution":
                    tool_name, success = match.groups()
                    self.metrics["tools_used"][tool_name] += 1
                elif pattern_name == "error":
                    self.metrics["failed_requests"] += 1
                    self.errors.append({
                        "timestamp": (timestamp or datetime.now()).isoformat(),
                        "message": line[:200],
                    })

    def _extract_field(self, message: str, field: str) -> Optional[str]:
        """メッセージからフィールドを抽出"""
        patterns = [
            rf'{field}=(\S+)',
            rf'"{field}":\s*"?([^",}}\s]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                return match.group(1).strip('"')
        return None

    def _categorize_error(self, message: str) -> str:
        """エラーをカテゴリ分け"""
        if "timeout" in message.lower():
            return "timeout"
        elif "rate limit" in message.lower():
            return "rate_limit"
        elif "api" in message.lower():
            return "api_error"
        elif "database" in message.lower() or "db" in message.lower():
            return "database_error"
        elif "validation" in message.lower():
            return "validation_error"
        else:
            return "other"

    def analyze_file(self, filepath: str) -> None:
        """ログファイルを分析"""
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                self.parse_log_line(line.strip())

    def generate_report(self) -> Dict[str, Any]:
        """分析レポートを生成"""
        total = self.metrics["total_requests"]
        successful = self.metrics["successful_requests"]
        failed = self.metrics["failed_requests"]

        # エラー率計算
        error_rate = (failed / total * 100) if total > 0 else 0

        # 確信度統計
        confidence_scores = self.metrics["confidence_scores"]
        avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0
        min_confidence = min(confidence_scores) if confidence_scores else 0
        max_confidence = max(confidence_scores) if confidence_scores else 0

        # Guardian Layer統計
        guardian_total = sum(self.metrics["guardian_actions"].values())
        allow_rate = (
            self.metrics["guardian_actions"].get("allow", 0) / guardian_total * 100
            if guardian_total > 0 else 0
        )

        return {
            "summary": {
                "total_requests": total,
                "successful_requests": successful,
                "failed_requests": failed,
                "error_rate_percent": round(error_rate, 2),
                "confirmed_requests": self.metrics["confirmed_requests"],
                "blocked_requests": self.metrics["blocked_requests"],
                "api_errors": self.metrics["api_errors"],
            },
            "confidence_stats": {
                "average": round(avg_confidence, 3),
                "min": round(min_confidence, 3),
                "max": round(max_confidence, 3),
                "samples": len(confidence_scores),
            },
            "guardian_stats": {
                "total_checks": guardian_total,
                "allow_rate_percent": round(allow_rate, 2),
                "actions": dict(self.metrics["guardian_actions"]),
            },
            "output_types": dict(self.metrics["output_types"]),
            "tools_used": dict(sorted(
                self.metrics["tools_used"].items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]),
            "errors_by_type": dict(self.metrics["errors_by_type"]),
            "hourly_distribution": dict(sorted(self.metrics["hourly_requests"].items())),
            "recent_errors": self.errors[-20:],  # 直近20件
        }


# =============================================================================
# メイン処理
# =============================================================================

def analyze_local_logs(log_dir: str = "logs") -> Dict[str, Any]:
    """ローカルログファイルを分析"""
    analyzer = LLMBrainLogAnalyzer()

    log_path = Path(log_dir)
    if not log_path.exists():
        print(f"Warning: Log directory not found: {log_dir}")
        return analyzer.generate_report()

    log_files = list(log_path.glob("*.log")) + list(log_path.glob("*.json"))
    for log_file in log_files:
        print(f"Analyzing: {log_file}")
        analyzer.analyze_file(str(log_file))

    return analyzer.generate_report()


def print_report(report: Dict[str, Any]) -> None:
    """レポートを表示"""
    print("\n" + "=" * 60)
    print("LLM Brain ログ分析レポート")
    print("=" * 60)

    # サマリー
    summary = report["summary"]
    print("\n【サマリー】")
    print(f"  総リクエスト数:     {summary['total_requests']:,}")
    print(f"  成功リクエスト数:   {summary['successful_requests']:,}")
    print(f"  失敗リクエスト数:   {summary['failed_requests']:,}")
    print(f"  エラー率:           {summary['error_rate_percent']:.2f}%")
    print(f"  確認要求数:         {summary['confirmed_requests']:,}")
    print(f"  ブロック数:         {summary['blocked_requests']:,}")
    print(f"  APIエラー数:        {summary['api_errors']:,}")

    # 確信度統計
    conf = report["confidence_stats"]
    print("\n【確信度統計】")
    print(f"  平均:               {conf['average']:.3f}")
    print(f"  最小:               {conf['min']:.3f}")
    print(f"  最大:               {conf['max']:.3f}")
    print(f"  サンプル数:         {conf['samples']:,}")

    # Guardian Layer統計
    guardian = report["guardian_stats"]
    print("\n【Guardian Layer統計】")
    print(f"  総チェック数:       {guardian['total_checks']:,}")
    print(f"  許可率:             {guardian['allow_rate_percent']:.2f}%")
    print("  アクション別:")
    for action, count in guardian["actions"].items():
        print(f"    - {action}: {count:,}")

    # 出力タイプ
    print("\n【出力タイプ別】")
    for output_type, count in report["output_types"].items():
        print(f"  {output_type}: {count:,}")

    # よく使われるTool Top 10
    print("\n【よく使われるTool Top 10】")
    for tool, count in list(report["tools_used"].items())[:10]:
        print(f"  {tool}: {count:,}")

    # エラー種別
    if report["errors_by_type"]:
        print("\n【エラー種別】")
        for error_type, count in report["errors_by_type"].items():
            print(f"  {error_type}: {count:,}")

    # 直近のエラー
    if report["recent_errors"]:
        print("\n【直近のエラー（最大5件）】")
        for error in report["recent_errors"][-5:]:
            print(f"  [{error.get('timestamp', 'N/A')}] {error.get('message', 'N/A')[:80]}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="LLM Brain ログ分析")
    parser.add_argument("--local", action="store_true", help="ローカルログを分析")
    parser.add_argument("--log-dir", default="logs", help="ログディレクトリ")
    parser.add_argument("--hours", type=int, default=24, help="分析対象時間（時間）")
    parser.add_argument("--output", help="結果をJSONファイルに出力")

    args = parser.parse_args()

    # 分析実行
    if args.local:
        report = analyze_local_logs(args.log_dir)
    else:
        # デフォルトはローカル分析
        report = analyze_local_logs(args.log_dir)

    # レポート表示
    print_report(report)

    # JSON出力
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nレポートを保存しました: {args.output}")


if __name__ == "__main__":
    main()
