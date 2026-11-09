"""Fixed ordinary proof-slot actions derived from approved theorem headers, not archive bodies."""


COMMON = (("exact_library", "exact?"), ("apply_library", "apply?"), ("ordinary_grind", "grind"),
          ("ordinary_omega", "omega"), ("ordinary_norm_num", "norm_num"))
P104_PLAIN = """have hle : a ≤ a ^ p := by
  calc
    a = a ^ 1 := (pow_one a).symm
    _ ≤ a ^ p := Nat.pow_le_pow_right h₀ h₁.pos
exact Int.natCast_dvd_natCast.mp (by
  simpa only [Int.ofNat_sub hle, Nat.cast_pow] using Int.prime_dvd_pow_self_sub h₁ (a : ℤ))"""
P113_PLAIN = """have H (k : ℕ) : ∃ t : ℕ, (3 : ℕ) ^ ((2 : ℕ) ^ (k + 1)) = 1 + (2 : ℕ) ^ (k + 3) * (2 * t + 1) := by
  induction k with
  | zero => exact ⟨0, by norm_num⟩
  | succ k ih =>
    obtain ⟨t, ht⟩ := ih
    refine ⟨t + 2 ^ (k + 1) * (2 * t + 1) ^ 2, ?_⟩
    change (3 : ℕ) ^ ((2 : ℕ) ^ ((k + 1) + 1)) =
      1 + (2 : ℕ) ^ ((k + 1) + 3) * (2 * (t + 2 ^ (k + 1) * (2 * t + 1) ^ 2) + 1)
    rw [pow_succ (2 : ℕ) (k + 1), pow_mul, ht]
    simp only [Nat.add_assoc, pow_add]
    ring
obtain ⟨k, rfl⟩ := Nat.exists_eq_succ_of_ne_zero h₀.ne'
obtain ⟨t, ht⟩ := H k
change ((3 : ℕ) ^ ((2 : ℕ) ^ (k + 1)) - 1) % ((2 : ℕ) ^ (k + 1 + 3)) = (2 : ℕ) ^ (k + 3)
have hmod : (2 : ℕ) ^ (k + 1 + 3) = 2 * 2 ^ (k + 3) := by
  simp only [Nat.add_assoc, pow_add]
  ring
have hdiff : 1 + (2 : ℕ) ^ (k + 3) * (2 * t + 1) - 1 = (2 * 2 ^ (k + 3)) * t + 2 ^ (k + 3) := by
  simp only [Nat.add_sub_cancel_left]
  ring
rw [ht, hmod, hdiff, Nat.mul_add_mod]
exact Nat.mod_eq_of_lt (by
  have hp : 0 < (2 : ℕ) ^ (k + 3) := by positivity
  omega)"""
P41_PLAIN = """induction n with
| zero => omega
| succ n ih =>
  have hp : 0 < (10 : ℕ) ^ n := by positivity
  by_cases hn : n = 0
  · subst n
    norm_num
  · obtain ⟨k, hk⟩ := ih (Nat.pos_of_ne_zero hn)
    refine ⟨10 * k + 1, ?_⟩
    simp only [pow_succ]
    omega"""


def actions(case):
    if case == "p104":
        return COMMON + (("signature_fermat_cast", "exact_mod_cast Int.prime_dvd_pow_self_sub h₁ (a : ℤ)"),
                         ("plain_whole_slot", P104_PLAIN))
    if case == "p113":
        return COMMON + (("ordinary_induction_pow_grind", "induction n <;> grind [pow_succ]"),
                         ("plain_whole_slot", P113_PLAIN))
    if case == "p41":
        return COMMON + (("ordinary_induction_pow_grind", "induction n <;> grind [pow_succ]"),
                         ("signature_pow_difference", "exact Nat.sub_one_dvd_pow_sub_one 10 n"),
                         ("plain_whole_slot", P41_PLAIN))
    raise ValueError("Unknown reviewed target")
