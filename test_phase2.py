#!/usr/bin/env python3
"""Quick validation test for Thompson Optimizer"""

import sys
sys.path.insert(0, '.')

import tempfile
from app.thompson_optimizer import ThompsonOptimizer, OptimizationStatus

print("Testing Thompson Sampling Optimizer (Phase 2)...")
print("=" * 60)

with tempfile.TemporaryDirectory() as tmpdir:
    # Test 1: Initialization
    opt = ThompsonOptimizer(state_path=tmpdir, max_iterations=100)
    assert opt.status == OptimizationStatus.IDLE
    print("✓ Test 1: Initialization")
    
    # Test 2: Start optimization
    result = opt.start_optimization(
        parameter_name='hint_frequency',
        variants={'freq_1': 1, 'freq_2': 2, 'freq_3': 3}
    )
    assert result['success'] is True
    print("✓ Test 2: Start optimization")
    
    # Test 3: Thompson Sampling
    selection = opt.select_variant()
    assert selection is not None
    print(f"✓ Test 3: Selected variant: {selection['variant_name']}")
    
    # Test 4: Report outcome
    outcome = opt.report_outcome(success=True)
    assert outcome['success'] is True
    print("✓ Test 4: Report outcome")
    
    # Test 5: Exploration
    for _ in range(15):
        opt.select_variant()
        opt.report_outcome(success=True)
    print(f"✓ Test 5: Explored {opt.iteration} iterations")
    
    # Test 6: Convergence
    opt2 = ThompsonOptimizer(state_path=tmpdir)
    opt2.start_optimization('test', {'good': 1, 'bad': 2})
    opt2.variants['good'].alpha = 20.0
    opt2.variants['good'].trials = 20
    opt2.variants['bad'].alpha = 5.0
    opt2.variants['bad'].trials = 20
    opt2.iteration = 25
    conv = opt2._check_convergence()
    assert conv['converged']
    print("✓ Test 6: Convergence detection")
    
    # Test 7: Recommendation
    rec = opt2.get_recommendation()
    assert rec is not None
    print(f"✓ Test 7: Recommendation: {rec['recommended_variant']}")
    
    # Test 8: Approval
    approval = opt2.approve_recommendation(True, "test")
    assert approval['success']
    print("✓ Test 8: HITL approval")
    
    # Test 9: Circuit breaker
    opt3 = ThompsonOptimizer(state_path=tmpdir)
    opt3.start_optimization('param', {'v1': 1})
    opt3.select_variant()
    result = opt3.report_outcome(False, metrics={'error_rate': 0.15})
    assert result['triggered']
    print("✓ Test 9: Circuit breaker")
    
    # Test 10: Rate limit
    opt4 = ThompsonOptimizer(state_path=tmpdir)
    opt4.optimizations_this_hour = 50
    result = opt4.start_optimization('p', {'v': 1})
    assert not result['success']
    print("✓ Test 10: Rate limiting")

print("=" * 60)
print("ALL TESTS PASSED ✓")
print("Phase 2 Thompson Sampling Optimizer is working correctly!")
