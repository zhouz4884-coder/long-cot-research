import Lean

set_option autoImplicit false
set_option warningAsError true
set_option maxHeartbeats 200000

-- Statement from google-deepmind/miniF2F f0a20e1, MiniF2F/Test.lean.
-- The source declaration has no accepted proof. This independently authored
-- proof uses Lean core, without importing the source declaration or Mathlib.
theorem d38_competition_residue (x y : Int) : 4 * x ^ 3 - 7 * y ^ 3 ≠ 2003 := by
  intro asserted
  have onlyX : (4 * x ^ 3) % 7 = 1 := by
    have reduced := congrArg (fun a : Int => a % 7) asserted
    change (4 * x ^ 3 - 7 * y ^ 3) % 7 = (2003 : Int) % 7 at reduced
    rw [Int.sub_emod, Int.mul_emod_right, Int.sub_zero, Int.emod_emod] at reduced
    exact reduced
  have cube : (x ^ 3) % 7 = ((x % 7) ^ 3) % 7 := by
    simp only [Int.pow_succ, Int.pow_zero, Int.one_mul]
    calc
      (x * x * x) % 7 = ((x * x) % 7 * (x % 7)) % 7 := Int.mul_emod (x * x) x 7
      _ = (((x % 7) * (x % 7)) % 7 * (x % 7)) % 7 := by rw [Int.mul_emod x x 7]
      _ = ((x % 7) * (x % 7) * (x % 7)) % 7 := by
        rw [Int.mul_emod (((x % 7) * (x % 7)) % 7) (x % 7) 7]
        simpa only [Int.emod_emod] using (Int.mul_emod ((x % 7) * (x % 7)) (x % 7) 7).symm
  have onlyResidue : (4 * (x % 7) ^ 3) % 7 = 1 := by
    rw [Int.mul_emod 4 (x ^ 3) 7, cube] at onlyX
    exact (Int.mul_emod 4 ((x % 7) ^ 3) 7).trans onlyX
  have lo : 0 ≤ x % 7 := Int.emod_nonneg x (by decide)
  have hi : x % 7 < 7 := Int.emod_lt_of_pos x (by decide)
  have cases : x % 7 = 0 ∨ x % 7 = 1 ∨ x % 7 = 2 ∨ x % 7 = 3 ∨ x % 7 = 4 ∨ x % 7 = 5 ∨ x % 7 = 6 := by omega
  rcases cases with h | h | h | h | h | h | h <;> rw [h] at onlyResidue <;> contradiction

#print axioms d38_competition_residue
