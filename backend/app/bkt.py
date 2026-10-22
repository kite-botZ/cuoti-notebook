"""BKT 认知诊断：把一次作答换算成知识点掌握度的变化。

## 为什么不用"做对率"

做对率 = 正确次数 / 总次数，看起来最直观，但有两个硬伤：

1. 它一视同仁。同一道题，答对只说明"可能掌握了"，答错却相当说明问题；
   而且难题答对和送分题答对在做对率里权重完全一样。
2. 没做过的知识点是 0/0，算不出值，于是没法参与"接下来该练哪个知识点"的排序——
   而这恰恰是自适应选题最需要的信息。

## BKT 在做什么

BKT（Bayesian Knowledge Tracing）把"掌握程度"建模成一个概率 `p`：
**这个知识点已经掌握的概率**。每次作答走两步：

- **证据更新（贝叶斯）**：答对 → 更可能是掌握了；答错 → 更可能是没掌握。
  但答对可能是蒙的（guess），答错可能是手滑（slip），所以一次作答不会把 p 打死到 0 或 1，
  连续多次同向作答才会明显移动——这正是我们要的抗抖动性质。
- **学习转移**：练过一次本身就有学会的机会，p 再往 1 挪一点。

四个参数：

| 参数 | 含义 | 默认值 |
| --- | --- | --- |
| `p_init`  | 新知识点的初始掌握概率 | 0.30 |
| `p_learn` | 学习率：一次练习真正学会的概率 | 0.15 |
| `p_slip`  | 失误率：会了却答错的概率 | 0.10 |
| `p_guess` | 猜测率：不会却答对的概率 | 0.25 |

默认值取的是 BKT 文献里的常用取值。没有做按知识点拟合（EM）：
拟合要每个知识点都有几十次以上作答才稳，冷启动阶段硬拟合只会过拟合，
参数表还会变成一份没人敢动的魔数。等数据够了再上，接口不用改。

## 两个必须守住的性质

- `1 - p_slip > p_guess`：这是 BKT 可辨识的前提。不满足的话，
  答对反而会**降低**掌握度，模型就反了。见 `BktParams.validate()`。
- 连续答对 → p 单调升；连续答错 → p 单调降。见 `tests/test_bkt.py`。

## 三个容易被当成 bug 的地方

**1. 一直答错，掌握度不会归零。** 稳态在 **0.173** 附近，不是 0.01。
因为学习转移是**每次作答机会都施加**的（标准 BKT 就是这样）：你答错的同时，
模型也认为"你至少又练了一次，可能学会了一点"。两个力一推一拉，就有了非零不动点。
这是有意保留的：一次手滑不该把学生判成"零掌握"，而且真实的遗忘/学会
也不该由单次作答决定。

**2. 掌握度会在 0.99 饱和。** 从 0.30 开始连续答对是
`0.30 → 0.67 → 0.90 → 0.97 → 0.99 → 0.99…`，第 4 次之后不再上升。
所以"连续答对 → 严格单调上升"只在饱和前成立，测试里断言的是
**单调不减 + 上界收敛**。

**3. `p_guess = 0.25` 对应四选一。** 判断题的真实猜测率是 0.5，
填空题接近 0，这里用一个统一值是一种简化。误差方向可以明说：
判断题答对会**高估**掌握度，填空题答对会**低估**。
按题型给 guess 是改进方向，但那需要分题型的作答数据来校验，
现在没有，所以不引入一张没校验过的参数表。
"""

from __future__ import annotations

from dataclasses import dataclass

# 掌握度的上下界。不让 p 取到 0 或 1：
# 一旦是 0，答对的似然就是 0（"绝对没掌握的人不可能答对"），
# 贝叶斯分母为 0，模型再也爬不出来。
P_MIN = 0.01
P_MAX = 0.99


@dataclass(frozen=True)
class BktParams:
    """BKT 的四个参数。"""

    p_init: float = 0.30
    p_learn: float = 0.15
    p_slip: float = 0.10
    p_guess: float = 0.25

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        for name in ("p_init", "p_learn", "p_slip", "p_guess"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{name}={v} 必须落在 [0, 1]")
        # 可辨识性：答对必须把 p 往上推。推导见 posterior()。
        if 1.0 - self.p_slip <= self.p_guess:
            raise ValueError(
                f"参数不可辨识：需要 1 - p_slip > p_guess，"
                f"当前 {1.0 - self.p_slip:.2f} <= {self.p_guess:.2f}，"
                f"这样答对反而会让掌握度下降"
            )


DEFAULT_PARAMS = BktParams()


def _clamp(p: float) -> float:
    return min(P_MAX, max(P_MIN, p))


def posterior(p: float, is_correct: bool, params: BktParams = DEFAULT_PARAMS) -> float:
    """证据更新：在已有掌握度 `p` 下观察到一次作答，求后验。

    答对：P(掌握 | 答对) = P(答对|掌握)·P(掌握) / P(答对)
         = p(1-slip) / [p(1-slip) + (1-p)guess]
    答错：P(掌握 | 答错) = p·slip / [p·slip + (1-p)(1-guess)]

    由第一式可以看出来：只有当 `1 - slip > guess` 时，后验才大于先验 `p`。
    这就是 `BktParams.validate()` 拦的那个条件。
    """
    p = _clamp(p)
    if is_correct:
        num = p * (1.0 - params.p_slip)
        den = num + (1.0 - p) * params.p_guess
    else:
        num = p * params.p_slip
        den = num + (1.0 - p) * (1.0 - params.p_guess)
    if den <= 0.0:  # 参数被外部改坏时的兜底，正常走不到
        return p
    return _clamp(num / den)


def learn(p: float, weight: float = 1.0, params: BktParams = DEFAULT_PARAMS) -> float:
    """学习转移：练过一次，p 往 1 走 `p_learn` 那么多（按考察权重缩放）。"""
    p = _clamp(p)
    weight = _clamp_weight(weight)
    return _clamp(p + weight * (1.0 - p) * params.p_learn)


def _clamp_weight(weight: float) -> float:
    """考察权重钳到 [0, 1]。权重是"这道题有多考这个知识点"，不该超过 1。"""
    try:
        w = float(weight)
    except (TypeError, ValueError):
        return 1.0
    return min(1.0, max(0.0, w))


def apply_attempt(
    p: float,
    is_correct: bool,
    weight: float = 1.0,
    params: BktParams = DEFAULT_PARAMS,
) -> float:
    """一次作答对某个知识点掌握度的完整更新：先证据更新，再学习转移。

    `weight` 是 `question_knowledge_points.weight`——这道题对这个知识点的考察权重。
    它的作用是**把这次作答的影响按权重缩放**，收敛到权重为 0 时"等于没做这道题"：

    - 证据更新：`p + w·(后验 - p)`，即把后验往先验方向收。
      直接用后验的话，一道只沾了 10% 这个知识点的题，会像完全考它一样推动掌握度。
    - 学习转移：`p + w·(1-p)·p_learn`，只沾一点就只学到一点。

    权重缩放是一个工程上的简化（标准 BKT 没有这个概念，因为标准 BKT 假定
    一道题只对应一个知识点）。它的好处是单调、可解释，且 w=1 时**完全等价于标准 BKT**。
    """
    p = _clamp(p)
    weight = _clamp_weight(weight)

    # 一次作答的影响：先算后验，再按权重往先验收缩
    after_evidence = posterior(p, is_correct, params)
    p = _clamp(p + weight * (after_evidence - p))

    # 再给一次学习机会
    return learn(p, weight, params)


# ============================================================
# 掌握度的对外表述
# ============================================================

# 分档阈值。这几个数是**按模型实际输出标定**的，不是随手取的 0.25/0.5/0.75：
# 从 p_init=0.30 出发，连续答对是 0.30 → 0.67 → 0.90 → 0.97 → 0.99，
# 所以阈值取成这样，档位才会跟着"练了几次"合理地走：
#
#   0 次 → 未掌握   1 次答对 → 薄弱   2 次答对 → 基本掌握   3 次答对 → 熟练
#
# 注意 p_init = 0.30 落在"未掌握"里：没做过的知识点本来就该显示成没掌握，
# 显示成"一般"的话，冷启动时所有知识点看起来都还行，自适应选题就没有目标了。
LEVELS: tuple[tuple[float, str], ...] = (
    (0.90, "熟练"),
    (0.72, "基本掌握"),
    (0.45, "薄弱"),
    (0.0, "未掌握"),
)


def level(p: float) -> str:
    """把 0~1 的掌握度映射成给人看的档位。"""
    p = _clamp(p)
    for threshold, name in LEVELS:
        if p >= threshold:
            return name
    return "未掌握"


def need(p: float) -> float:
    """还有多少提升空间。自适应选题按它排序，越大越该练。"""
    return 1.0 - _clamp(p)


def is_mastered(p: float) -> bool:
    return _clamp(p) >= LEVELS[0][0]