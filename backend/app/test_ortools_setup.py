"""
test_ortools_setup.py

Throwaway environment check — not part of the app.
Creates a trivial CP-SAT model to confirm OR-Tools is installed and working.

Model:
  - Two integer variables x, y in [0, 10]
  - Constraint: x + y == 7
  - Objective: minimize x

Expected output: x = 0, y = 7  (or any pair summing to 7)
"""

from ortools.sat.python import cp_model
def main():
    model = cp_model.CpModel()

    # Two integer variables
    x = model.new_int_var(0, 10, "x")
    y = model.new_int_var(0, 10, "y")

    # One constraint
    model.add(x + y == 7)

    # Optional: minimize x so the result is deterministic
    model.minimize(x)

    solver = cp_model.CpSolver()
    status = solver.solve(model)

    status_name = solver.status_name(status)
    print(f"Status : {status_name}")

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f"x = {solver.value(x)}")
        print(f"y = {solver.value(y)}")
        print("OR-Tools CP-SAT is working correctly.")
    else:
        print("No solution found — something is wrong with the installation.")


if __name__ == "__main__":
    main()
