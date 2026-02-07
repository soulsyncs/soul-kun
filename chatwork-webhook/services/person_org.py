"""services/person_org.py - 人物情報・組織図サービス

Phase 11-3: main.pyから抽出された人物情報管理・組織図クエリ機能。

依存: infra/db.py (get_pool), lib/person_service (PersonService, OrgChartService)
"""

from infra.db import get_pool

try:
    from lib.person_service import PersonService, OrgChartService, normalize_person_name as _svc_normalize_person_name
    USE_PERSON_SERVICE = True
except ImportError:
    USE_PERSON_SERVICE = False

# PersonService / OrgChartService の遅延初期化
_person_service = None
_org_chart_service = None



def _get_person_service():
    """PersonServiceのシングルトンインスタンスを取得"""
    global _person_service
    if _person_service is None and USE_PERSON_SERVICE:
        _person_service = PersonService(get_pool=get_pool)
    return _person_service

def _get_org_chart_service():
    """OrgChartServiceのシングルトンインスタンスを取得"""
    global _org_chart_service
    if _org_chart_service is None and USE_PERSON_SERVICE:
        _org_chart_service = OrgChartService(get_pool=get_pool)
    return _org_chart_service

def save_person_attribute(person_name, attribute_type, attribute_value, source="conversation"):
    """人物属性を保存（lib/person_service.py に委譲）"""
    return _get_person_service().save_person_attribute(person_name, attribute_type, attribute_value, source)

def get_person_info(person_name):
    """人物情報を取得（lib/person_service.py に委譲）"""
    return _get_person_service().get_person_info(person_name)

def normalize_person_name(name):
    """人物名を正規化（lib/person_service.py に委譲）"""
    return _svc_normalize_person_name(name)

def search_person_by_partial_name(partial_name):
    """部分一致で人物を検索（lib/person_service.py に委譲）"""
    return _get_person_service().search_person_by_partial_name(partial_name)

def delete_person(person_name):
    """人物を削除（lib/person_service.py に委譲）"""
    return _get_person_service().delete_person(person_name)

def get_all_persons_summary():
    """全人物サマリーを取得（lib/person_service.py に委譲）"""
    return _get_person_service().get_all_persons_summary()

def get_org_chart_overview():
    """組織図の全体構造を取得（lib/person_service.py に委譲）"""
    svc = _get_org_chart_service()
    if svc:
        return svc.get_org_chart_overview()
    return []

def search_department_by_name(partial_name):
    """部署名で検索（lib/person_service.py に委譲）"""
    svc = _get_org_chart_service()
    if svc:
        return svc.search_department_by_name(partial_name)
    return []

def get_department_members(dept_name):
    """部署のメンバー一覧を取得（lib/person_service.py に委譲）"""
    svc = _get_org_chart_service()
    if svc:
        return svc.get_department_members(dept_name)
    return None, []

def resolve_person_name(name):
    """部分的な名前から正式な名前を解決（ユーティリティ関数）"""
    # ★★★ v6.8.6: 名前を正規化してから検索 ★★★
    normalized_name = normalize_person_name(name)
    
    # まず正規化した名前で完全一致を試す
    info = get_person_info(normalized_name)
    if info:
        return normalized_name
    
    # 元の名前で完全一致を試す
    info = get_person_info(name)
    if info:
        return name
    
    # 正規化した名前で部分一致検索
    matches = search_person_by_partial_name(normalized_name)
    if matches:
        return matches[0]
    
    # 元の名前で部分一致検索
    matches = search_person_by_partial_name(name)
    if matches:
        return matches[0]
    
    return name

def parse_attribute_string(attr_str):
    """
    AI司令塔が返す文字列形式のattributeをパースする
    
    入力例: "黒沼 賢人: 部署=広報部, 役職=部長兼戦略設計責任者"
    出力例: [{"person": "黒沼 賢人", "type": "部署", "value": "広報部"}, ...]
    """
    results = []
    
    try:
        # "黒沼 賢人: 部署=広報部, 役職=部長兼戦略設計責任者"
        if ":" in attr_str:
            parts = attr_str.split(":", 1)
            person = parts[0].strip()
            attrs_part = parts[1].strip() if len(parts) > 1 else ""
            
            # "部署=広報部, 役職=部長兼戦略設計責任者"
            for attr_pair in attrs_part.split(","):
                attr_pair = attr_pair.strip()
                if "=" in attr_pair:
                    key_value = attr_pair.split("=", 1)
                    attr_type = key_value[0].strip()
                    attr_value = key_value[1].strip() if len(key_value) > 1 else ""
                    if attr_type and attr_value:
                        results.append({
                            "person": person,
                            "type": attr_type,
                            "value": attr_value
                        })
        else:
            # ":" がない場合（シンプルな形式）
            # 例: "黒沼さんは営業部の部長です" のような形式は想定外
            print(f"   ⚠️ パースできない形式: {attr_str}")
    except Exception as e:
        print(f"   ❌ パースエラー: {e}")
    
    return results
