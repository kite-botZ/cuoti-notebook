"""BKT 数学部分的单元测试：不碰数据库，只验公式的性质。

为什么要专门测"性质"而不是测具体数值：
具体数值可以照着实现抄一遍编出来，测了等于没测。而性质是**独立于实现**的——
任何一次重构，只要把"答对不会让掌握度下降"改坏了，这里就会红。
"""

import pytest

from app import bkt
from app.bkt import BktParams

P = BktParams()


# ============================================================
# 参数合法性
# ============================================================

def test_default_params_are_identifiable():
    """默认参数必须满足 1 - slip > guess，否则模型方向是反的。"""
    assert 1.0 - P.p_slip > P.p_guess


@pytest.mark.parametrize("slip,guess", [(0.5, 0.5), (0.2, 0.8), (0.9, 0.1)])
def test_rejects_non_identifiable_params(slip, guess):
    """故意给一组会翻转方向的参数，必须被拦下来。

    (0.2, 0.8)：1 - 0.2 = 0.8 <= 0.8，刚好不满足严格大于。
    """
    with pytest.raises(ValueError, match="不可辨识"):
        BktParams(p_slip=slip, p_guess=guess)


@pytest.mark.parametrize("field", ["p_init", "p_learn", "p_slip", "p_guess"])
def test_rejects_out_of_range(field):
    with pytest.raises(ValueError, match="必须落在"):
        BktParams(**{field: 1.5})


# ============================================================
# 证据更新：方向必须对
# ============================================================

@pytest.mark.parametrize("p", [0.05, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95])
def test_correct_always_raises_mastery(p):
    """答对必须让掌握度上升——这是整个诊断的立身之本。"""
    assert bkt.posterior(p, True) > p


@pytest.mark.parametrize("p", [0.05, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95])
def test_wrong_always_lowers_mastery(p):
    assert bkt.posterior(p, False) < p


def test_posterior_stays_in_range():
    for p in [0.0, 0.01, 0.5, 0.99, 1.0]:
        for is_correct in (True, False):
            got = bkt.posterior(p, is_correct)
            assert bkt.P_MIN <= got <= bkt.P_MAX


# ============================================================
# 连续作答：单调、有界、抗抖动
# ============================================================

def test_repeated_correct_is_monotone_and_approaches_ceiling():
    """连续答对：单调不减，并且收敛到 0.99（不会越过上界）。

    注意这里断言的是**单调不减**而不是严格递增：掌握度会在 P_MAX 饱和，
    饱和之后再加练习也不会涨。一开始写成"严格递增"是我的测试写错了，
    不是模型错了——把一个必然饱和的量断言成永远增长，测的是一个不存在的性质。
    """
    p = P.p_init
    seen = [p]
    for _ in range(30):
        nxt = bkt.apply_attempt(p, True)
        assert nxt >= p, "连续答对时掌握度不能下降"
        assert nxt <= bkt.P_MAX
        p = nxt
        seen.append(p)

    assert p == pytest.approx(bkt.P_MAX), "答对 30 次之后应该顶到上界"
    # 前 3 次必须是真的在涨（还没饱和），否则模型等于没反应
    assert seen[1] > seen[0] and seen[2] > seen[1] and seen[3] > seen[2]
    # 增量递减：越接近 1 提升越慢，第 5 次起归零
    deltas = [seen[i + 1] - seen[i] for i in range(4)]
    assert deltas[0] > deltas[1] > deltas[2] > deltas[3]
    assert seen[5] == pytest.approx(seen[4]), "第 5 次开始应该已经饱和"


def test_mastery_progression_matches_display_levels():
    """档位要跟着"练了几次"走——这是把阈值和模型输出绑定在一起的回归测试。

    从 p_init 出发连续答对，档位应该是 未掌握 → 薄弱 → 基本掌握 → 熟练。
    如果谁改了 `p_learn` 或档位阈值让这个序列错位（比如答对一次就"熟练"），
    这条会红。
    """
    p = P.p_init
    assert bkt.level(p) == "未掌握"

    p = bkt.apply_attempt(p, True)
    assert bkt.level(p) == "薄弱", f"答对 1 次是 {p:.3f}，档位应该还是薄弱"

    p = bkt.apply_attempt(p, True)
    assert bkt.level(p) == "基本掌握", f"答对 2 次是 {p:.3f}，档位应该到基本掌握"

    p = bkt.apply_attempt(p, True)
    assert bkt.level(p) == "熟练", f"答对 3 次是 {p:.3f}，档位应该到熟练"


def test_repeated_wrong_converges_to_nonzero_equilibrium():
    """一直答错：单调下降到 0.17 附近的不动点，而不是归零。

    这个非零下界是标准 BKT 的固有性质：学习转移在**每次作答机会**都施加，
    答错的同时也承认"又练了一次"。测试把它钉住，是为了让以后看到
    "答错 30 次掌握度还有 0.17"的人知道这是设计，不是漏了个清零。
    """
    p = 0.95
    prev = p
    for _ in range(40):
        p = bkt.apply_attempt(p, False)
        assert p <= prev, "连续答错时掌握度不能上升"
        prev = p
    assert p == pytest.approx(0.173, abs=0.005), f"不动点跑到了 {p:.4f}"
    assert bkt.level(p) == "未掌握", "一直答错必须落在未掌握档"


def test_single_slip_does_not_destroy_mastery():
    """已经练熟的知识点，偶尔错一次不该被打回原形。

    这是 BKT 相对"做对率"的核心优势：slip 参数给了单次失误容错。
    如果这条挂了，说明有人把 slip 去掉了，模型会变得对单次手滑极度敏感。
    """
    p = bkt.apply_attempt(0.90, False)
    assert p > 0.6, f"错一次就把 0.90 打到 {p:.3f}，容错太差"
    assert bkt.level(p) != "熟练", "但错一次也不该还是熟练"


def test_single_lucky_guess_does_not_grant_mastery():
    """完全没掌握时蒙对一次，不该直接算掌握（熟练）。

    从 p_init=0.30 蒙对一次得到 0.666。这个数看着偏高，但它是贝叶斯的正确结果：
    四选一情况下 P(答对|没掌握)=0.25、P(答对|掌握)=0.90，似然比 9 倍，
    先验 0.30 被推到 0.61，再叠加一次学习转移就是 0.67。
    所以这里断言的不是"涨得少"，而是**涨一次不足以判定掌握**。
    """
    p = bkt.apply_attempt(P.p_init, True)
    assert p < 0.72, f"蒙对一次就涨到 {p:.3f}，已经跨进「基本掌握」档了"
    assert bkt.level(p) != "熟练"
    assert bkt.is_mastered(p) is False


# ============================================================
# 考察权重
# ============================================================

def test_zero_weight_means_no_change():
    """权重 0 = 这道题完全不考这个知识点，作答不该影响它。"""
    for p in (0.2, 0.5, 0.8):
        assert bkt.apply_attempt(p, True, weight=0.0) == pytest.approx(p, abs=1e-9)
        assert bkt.apply_attempt(p, False, weight=0.0) == pytest.approx(p, abs=1e-9)


def test_full_weight_equals_standard_bkt():
    """权重 1 时必须和标准 BKT 完全一致（先证据更新、再学习转移）。"""
    for p in (0.2, 0.5, 0.8):
        for is_correct in (True, False):
            expected = bkt.learn(bkt.posterior(p, is_correct), 1.0)
            assert bkt.apply_attempt(p, is_correct, weight=1.0) == pytest.approx(expected)


def test_weight_scales_the_effect_monotonically():
    """权重越大，同一次作答带来的变化越大。"""
    for is_correct in (True, False):
        values = [bkt.apply_attempt(0.5, is_correct, weight=w)
                  for w in (0.0, 0.25, 0.5, 0.75, 1.0)]
        if is_correct:
            assert values == sorted(values), "答对时权重越大掌握度应越高"
        else:
            assert values == sorted(values, reverse=True), "答错时权重越大掌握度应越低"


def test_weight_is_clamped():
    """权重超出 [0,1] 要被钳住，不能放大成"一道题顶三道题"。"""
    assert bkt.apply_attempt(0.5, True, weight=5.0) == pytest.approx(
        bkt.apply_attempt(0.5, True, weight=1.0)
    )
    assert bkt.apply_attempt(0.5, True, weight=-3.0) == pytest.approx(0.5)
    # 非法权重退回 1.0（默认按"完全考查"处理），而不是抛异常中断判题
    assert bkt.apply_attempt(0.5, True, weight="abc") == pytest.approx(
        bkt.apply_attempt(0.5, True, weight=1.0)
    )


# ============================================================
# 对外表述
# ============================================================

@pytest.mark.parametrize("p,expected", [
    (0.0, "未掌握"),
    (0.44, "未掌握"),
    (0.45, "薄弱"),
    (0.66, "薄弱"),
    (0.72, "基本掌握"),
    (0.89, "基本掌握"),
    (0.90, "熟练"),
    (1.0, "熟练"),
])
def test_level_boundaries(p, expected):
    assert bkt.level(p) == expected


def test_new_kp_starts_as_not_mastered():
    """没做过的知识点应该显示"未掌握"，而不是"一般"。

    p_init=0.30 必须落在"未掌握"档里，否则冷启动时所有知识点看起来都还行，
    自适应选题就没有明确的目标了。
    """
    assert bkt.level(P.p_init) == "未掌握"


def test_need_is_complement_of_mastery():
    for p in (0.01, 0.3, 0.75, 0.99):
        assert bkt.need(p) == pytest.approx(1.0 - p)


def test_need_and_level_clamp_out_of_range_input():
    """越界的输入先被钳进 [P_MIN, P_MAX]，再算 need / level。

    这样"掌握度"这个量在任何路径上都不会泄漏出 0.01~0.99 之外的数
    （比如前端拿到负数画进度条会直接画到框外面去）。
    """
    assert bkt.need(0.0) == pytest.approx(1.0 - bkt.P_MIN)
    assert bkt.need(1.0) == pytest.approx(1.0 - bkt.P_MAX)
    assert bkt.level(-5.0) == "未掌握"
    assert bkt.level(5.0) == "熟练"


def test_is_mastered_matches_level():
    assert bkt.is_mastered(0.90) is True
    assert bkt.is_mastered(0.89) is False