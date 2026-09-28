from ortools.sat.python import cp_model  
model = cp_model.CpModel()
x = model.NewIntVar(0, 10, 'x')
y = model.NewIntVar(0, 10, 'y')
model.Add(x + y <= 10)
solver = cp_model.CpSolver()
solver.Solve(model)
print('x =', solver.Value(x))   
print('y =', solver.Value(y))