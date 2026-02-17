# lib/brain/core/brain_class.py
"""
SoulkunBrain クラス定義

全てのMixinを合成してSoulkunBrainクラスを構成する。
各Mixinが提供するメソッドを継承により統合。
"""

from lib.brain.core.initialization import InitializationMixin
from lib.brain.core.message_processing import MessageProcessingMixin
from lib.brain.core.proactive import ProactiveMixin
from lib.brain.core.memory_layer import MemoryLayerMixin
from lib.brain.core.state_layer import StateLayerMixin
from lib.brain.core.pipeline import PipelineMixin
from lib.brain.core.utilities import UtilitiesMixin


class SoulkunBrain(
    InitializationMixin,
    MessageProcessingMixin,
    ProactiveMixin,
    MemoryLayerMixin,
    StateLayerMixin,
    PipelineMixin,
    UtilitiesMixin,
):
    """
    ソウルくんの脳（中央処理装置）

    全てのユーザー入力を受け取り、記憶を参照し、意図を理解し、
    適切な機能を選択して実行する。

    使用例:
        brain = SoulkunBrain(pool=db_pool, org_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df")
        response = await brain.process_message(
            message="自分のタスク教えて",
            room_id="123456",
            account_id="7890",
            sender_name="菊地"
        )

    設計書: docs/13_brain_architecture.md

    【7つの鉄則】
    1. 全ての入力は脳を通る（バイパスルート禁止）
    2. 脳は全ての記憶にアクセスできる
    3. 脳が判断し、機能は実行するだけ
    4. 機能拡張しても脳の構造は変わらない
    5. 確認は脳の責務
    6. 状態管理は脳が統一管理
    7. 速度より正確性を優先
    """
    pass
