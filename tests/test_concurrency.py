import threading
from backend.background_analyzer import _limit_cache_size, _CACHE_LOCK

def test_cache_concurrency():
    test_dict = {}
    errors = []

    def worker(worker_id):
        try:
            for i in range(500):
                # Concurrently write to the dictionary under lock
                with _CACHE_LOCK:
                    key = f"key_{worker_id}_{i}"
                    test_dict[key] = f"val_{i}"
                
                # Concurrently evict from dictionary under lock
                _limit_cache_size(test_dict, max_size=50)
        except Exception as e:
            errors.append(e)

    threads = []
    # Spawn 10 concurrent threads doing rapid cache set & evict operations
    for t_id in range(10):
        t = threading.Thread(target=worker, args=(t_id,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # The reentrant locks must prevent dictionary mutation exceptions
    assert len(errors) == 0
