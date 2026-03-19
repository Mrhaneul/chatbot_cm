#!/usr/bin/env python3
"""
Simple test client to see response times from the chatbot API.
"""

import requests
import json

API_URL = "http://localhost:8000/chat"

def test_query(message: str, session_id: str = "test-session"):
    """Send a query and display timing info."""
    print(f"\n{'='*60}")
    print(f"Query: {message}")
    print(f"{'='*60}")
    
    payload = {
        "message": message,
        "session_id": session_id
    }
    
    try:
        response = requests.post(API_URL, json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            
            print(f"\n📝 Response:")
            print(f"{result['reply']}\n")
            
            print(f"⏱️  Timing Breakdown:")
            print(f"   Retrieval: {result.get('retrieval_time_ms', 0):.2f}ms")
            print(f"   LLM: {result.get('llm_time_ms', 0):.2f}ms")
            print(f"   Total: {result.get('total_time_ms', 0):.2f}ms")
            
            print(f"\n📊 Metadata:")
            print(f"   Source: {result['source']}")
            print(f"   Confidence: {result['confidence']:.2f}")
            if result.get('article_link'):
                print(f"   Article: {result['article_link']}")
            
            return result
        else:
            print(f"❌ Error: {response.status_code}")
            print(response.text)
            return None
            
    except requests.exceptions.Timeout:
        print("❌ Request timed out")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def run_test_suite():
    """Run a series of test queries."""
    print("\n" + "="*60)
    print("CHATBOT PERFORMANCE TEST")
    print("="*60)
    
    test_queries = [
        "Hi",
        "I can't access Cengage MindTap",
        "How do I access McGraw Hill Connect?",
        "What is Immediate Access?",
        "I'm having issues with Bedford",
    ]
    
    results = []
    
    for query in test_queries:
        result = test_query(query)
        if result:
            results.append({
                "query": query,
                "retrieval_ms": result.get('retrieval_time_ms', 0),
                "llm_ms": result.get('llm_time_ms', 0),
                "total_ms": result.get('total_time_ms', 0)
            })
        
        # Wait a bit between queries
        import time
        time.sleep(0.5)
    
    # Summary
    if results:
        print("\n\n" + "="*60)
        print("SUMMARY")
        print("="*60)
        
        avg_retrieval = sum(r['retrieval_ms'] for r in results) / len(results)
        avg_llm = sum(r['llm_ms'] for r in results) / len(results)
        avg_total = sum(r['total_ms'] for r in results) / len(results)
        
        print(f"\nAverage times across {len(results)} queries:")
        print(f"   Retrieval: {avg_retrieval:.2f}ms")
        print(f"   LLM: {avg_llm:.2f}ms")
        print(f"   Total: {avg_total:.2f}ms")
        
        fastest = min(results, key=lambda x: x['total_ms'])
        slowest = max(results, key=lambda x: x['total_ms'])
        
        print(f"\nFastest: {fastest['total_ms']:.2f}ms - '{fastest['query']}'")
        print(f"Slowest: {slowest['total_ms']:.2f}ms - '{slowest['query']}'")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # Single query mode
        query = " ".join(sys.argv[1:])
        test_query(query)
    else:
        # Full test suite
        run_test_suite()
