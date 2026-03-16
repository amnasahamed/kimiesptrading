#!/usr/bin/env python3
"""
Test script to verify Turbo Mode API is working correctly.
"""

import asyncio
import json
import sys

async def test_turbo_queue():
    """Test the turbo queue functions directly."""
    print("="*60)
    print("Testing Turbo Queue Module")
    print("="*60)
    
    from turbo_queue import get_queue_status, _load_queue
    
    # Test loading from file
    print("\n1. Loading queue from file...")
    queue = _load_queue()
    print(f"   ✓ Loaded {len(queue)} items from turbo_queue.json")
    
    if queue:
        print(f"\n2. Sample item:")
        sample = queue[0]
        print(f"   ID: {sample.get('id')}")
        print(f"   Symbol: {sample.get('symbol')}")
        print(f"   Status: {sample.get('status')}")
        print(f"   Direction: {sample.get('direction')}")
    
    # Test get_queue_status
    print(f"\n3. Testing get_queue_status()...")
    status = await get_queue_status()
    
    print(f"   Counts:")
    for key, val in status.get('counts', {}).items():
        print(f"      {key}: {val}")
    
    print(f"\n   Stats:")
    for key, val in status.get('stats', {}).items():
        print(f"      {key}: {val}")
    
    print(f"\n   Recent items: {len(status.get('recent_items', []))}")
    print(f"   All items: {len(status.get('all_items', []))}")
    
    return status


def test_api_endpoint():
    """Test the API endpoint."""
    print("\n" + "="*60)
    print("Testing API Endpoint")
    print("="*60)
    
    try:
        from fastapi.testclient import TestClient
        from chartink_webhook import app
        
        client = TestClient(app)
        
        print("\n1. Testing GET /api/turbo/status...")
        response = client.get('/api/turbo/status')
        
        print(f"   Status code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"   API status: {data.get('status')}")
            print(f"   Counts: {data.get('counts')}")
            print(f"   Recent items: {len(data.get('recent_items', []))}")
            return True
        else:
            print(f"   ✗ Error: {response.text}")
            return False
            
    except Exception as e:
        print(f"   ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("TURBO MODE DIAGNOSTIC TOOL")
    print("="*60)
    
    # Test queue module
    try:
        status = asyncio.run(test_turbo_queue())
        queue_ok = len(status.get('all_items', [])) > 0
    except Exception as e:
        print(f"\n✗ Queue test failed: {e}")
        queue_ok = False
    
    # Test API
    api_ok = test_api_endpoint()
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Queue Module: {'✓ OK' if queue_ok else '✗ FAILED'}")
    print(f"API Endpoint: {'✓ OK' if api_ok else '✗ FAILED'}")
    
    if queue_ok and api_ok:
        print("\n✓ All tests passed! Turbo Mode should be working.")
        print("\nIf you still can't see data in the dashboard:")
        print("1. Open browser console (F12) and check for errors")
        print("2. Click the Turbo Mode tab to trigger data load")
        print("3. Check if data appears after 3 seconds (auto-refresh)")
        return 0
    else:
        print("\n✗ Some tests failed. Please check the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
