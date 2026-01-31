#!/usr/bin/env python3
"""
Model Comparison Script
Tests different Ollama models and compares their performance.

Usage:
    python model_comparison.py

Requirements:
    - Ollama running on localhost:11434
    - Models pulled: ollama pull llama3.2, ollama pull mistral, etc.
"""

import requests
import time
import json
from typing import List, Dict
from statistics import mean, median, stdev

# Configuration
OLLAMA_URL = "http://localhost:11434/api/chat"
API_URL = "http://localhost:8000/chat"

# Models to test (make sure these are pulled in Ollama)
MODELS_TO_TEST = [
    "llama3.2",
    "llama3.2:1b",
    "llama3.1:8b",
    "mistral",
    "phi3",
]

# Test queries
TEST_QUERIES = [
    "I can't access Cengage MindTap",
    "How do I access my McGraw Hill Connect?",
    "What is Immediate Access?",
    "I'm having issues with my Bedford textbook",
    "How do I opt out of Immediate Access?",
]

# Sample context for testing
SAMPLE_CONTEXT = """
PROBLEM:
Student is opted into Immediate Access but cannot access Cengage MindTap textbook or assignments.

STEP-BY-STEP RESOLUTION:
1. Log in to Blackboard.
2. Open the correct course.
3. Click on the "Course Materials" tab in the left menu.
4. Click the MindTap registration or access link.
5. Open the appropriate week folder.
6. Select the MindTap chapter or assignment.
"""


def test_model_directly(model: str, query: str, context: str = "", num_runs: int = 3) -> Dict:
    """Test a model directly through Ollama API."""
    print(f"\n  Testing {model}...")
    
    times = []
    tokens_per_second = []
    
    for run in range(num_runs):
        messages = [
            {
                "role": "system",
                "content": "You are Lance, the Campus Store AI Assistant."
            }
        ]
        
        if context:
            messages[0]["content"] += f"\n\nContext:\n{context}"
        
        messages.append({
            "role": "user",
            "content": query
        })
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "num_predict": 512
            }
        }
        
        try:
            start = time.time()
            response = requests.post(OLLAMA_URL, json=payload, timeout=60)
            elapsed = time.time() - start
            
            if response.status_code == 200:
                result = response.json()
                reply = result["message"]["content"]
                
                # Calculate tokens per second (rough estimate)
                tokens = len(reply.split())
                tps = tokens / elapsed if elapsed > 0 else 0
                
                times.append(elapsed * 1000)  # Convert to ms
                tokens_per_second.append(tps)
                
                print(f"    Run {run + 1}: {elapsed * 1000:.0f}ms ({tps:.1f} tokens/sec)")
            else:
                print(f"    Run {run + 1}: ERROR - {response.status_code}")
                return None
                
        except requests.exceptions.Timeout:
            print(f"    Run {run + 1}: TIMEOUT")
            return None
        except Exception as e:
            print(f"    Run {run + 1}: ERROR - {e}")
            return None
    
    return {
        "model": model,
        "avg_time_ms": round(mean(times), 2),
        "median_time_ms": round(median(times), 2),
        "min_time_ms": round(min(times), 2),
        "max_time_ms": round(max(times), 2),
        "std_dev_ms": round(stdev(times), 2) if len(times) > 1 else 0,
        "avg_tokens_per_sec": round(mean(tokens_per_second), 2),
        "runs": num_runs
    }


def check_model_availability(model: str) -> bool:
    """Check if a model is available in Ollama."""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            model_names = [m["name"] for m in models]
            
            # Check exact match or with :latest tag
            return model in model_names or f"{model}:latest" in model_names
        return False
    except:
        return False


def run_comparison(queries: List[str] = None, with_context: bool = True):
    """Run full model comparison."""
    if queries is None:
        queries = TEST_QUERIES
    
    print("=" * 80)
    print("MODEL COMPARISON TEST")
    print("=" * 80)
    
    # Check Ollama availability
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code != 200:
            print("❌ Error: Cannot connect to Ollama. Make sure it's running.")
            return
    except:
        print("❌ Error: Cannot connect to Ollama at localhost:11434")
        print("   Start Ollama with: ollama serve")
        return
    
    # Check which models are available
    print("\n📦 Checking available models...")
    available_models = []
    for model in MODELS_TO_TEST:
        if check_model_availability(model):
            print(f"   ✓ {model}")
            available_models.append(model)
        else:
            print(f"   ✗ {model} (not found - run: ollama pull {model})")
    
    if not available_models:
        print("\n❌ No models available. Pull models with: ollama pull <model_name>")
        return
    
    print(f"\n📊 Testing {len(available_models)} models with {len(queries)} queries...")
    
    results = {}
    
    for query in queries:
        print(f"\n\n{'='*80}")
        print(f"Query: {query}")
        print(f"{'='*80}")
        
        query_results = []
        
        for model in available_models:
            context = SAMPLE_CONTEXT if with_context else ""
            result = test_model_directly(model, query, context, num_runs=3)
            
            if result:
                query_results.append(result)
        
        results[query] = query_results
    
    # Print summary
    print("\n\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    # Calculate averages across all queries for each model
    model_averages = {}
    for model in available_models:
        times = []
        tps_list = []
        
        for query_results in results.values():
            for result in query_results:
                if result["model"] == model:
                    times.append(result["avg_time_ms"])
                    tps_list.append(result["avg_tokens_per_sec"])
        
        if times:
            model_averages[model] = {
                "avg_time_ms": round(mean(times), 2),
                "avg_tokens_per_sec": round(mean(tps_list), 2)
            }
    
    # Sort by speed
    sorted_models = sorted(model_averages.items(), key=lambda x: x[1]["avg_time_ms"])
    
    print("\n🏆 Models ranked by speed (fastest to slowest):\n")
    for rank, (model, stats) in enumerate(sorted_models, 1):
        print(f"{rank}. {model:20s} - {stats['avg_time_ms']:7.0f}ms avg  ({stats['avg_tokens_per_sec']:.1f} tokens/sec)")
    
    # Recommendation
    print("\n💡 RECOMMENDATIONS:\n")
    fastest = sorted_models[0]
    print(f"   Fastest: {fastest[0]} ({fastest[1]['avg_time_ms']:.0f}ms)")
    
    if len(sorted_models) > 1:
        best_balance = sorted_models[1] if len(sorted_models) > 1 else sorted_models[0]
        print(f"   Best Balance: {best_balance[0]} ({best_balance[1]['avg_time_ms']:.0f}ms)")
    
    # Save results to JSON
    output_file = "model_comparison_results.json"
    with open(output_file, "w") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "results": results,
            "summary": model_averages,
            "ranking": [(model, stats) for model, stats in sorted_models]
        }, f, indent=2)
    
    print(f"\n📄 Full results saved to: {output_file}")


def quick_test(model: str = "llama3.2"):
    """Quick test of a single model."""
    print(f"\n🚀 Quick test of {model}...")
    
    if not check_model_availability(model):
        print(f"❌ Model {model} not found. Install with: ollama pull {model}")
        return
    
    query = "I can't access Cengage MindTap"
    result = test_model_directly(model, query, SAMPLE_CONTEXT, num_runs=3)
    
    if result:
        print(f"\n✅ Results:")
        print(f"   Average time: {result['avg_time_ms']:.0f}ms")
        print(f"   Tokens/sec: {result['avg_tokens_per_sec']:.1f}")
        print(f"   Range: {result['min_time_ms']:.0f}ms - {result['max_time_ms']:.0f}ms")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "quick":
            model = sys.argv[2] if len(sys.argv) > 2 else "llama3.2"
            quick_test(model)
        else:
            print("Usage:")
            print("  python model_comparison.py           # Full comparison")
            print("  python model_comparison.py quick     # Quick test with llama3.2")
            print("  python model_comparison.py quick mistral  # Quick test with specific model")
    else:
        run_comparison()
