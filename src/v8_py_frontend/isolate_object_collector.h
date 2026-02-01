#ifndef INCLUDE_MINI_RACER_ISOLATE_OBJECT_COLLECTOR_H
#define INCLUDE_MINI_RACER_ISOLATE_OBJECT_COLLECTOR_H

#include <v8-persistent-handle.h>
#include <v8-value.h>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <vector>
#include "isolate_manager.h"

namespace MiniRacer {

/** Deletes v8 objects.
 *
 * Things that want to delete v8 objects often don't own the isolate lock
 * (i.e., aren't running from the IsolateManager's message loop). From the V8
 * documentation, it's not clear if we can safely free v8 objects like a
 * v8::Global handle without the lock. As a rule, messing with v8::Isolate-owned
 * objects without holding the Isolate lock is not safe, and there is no
 * documentation indicating methods like v8::Global::~Global are exempt from
 * this rule. So this class delegates deletion to the Isolate message loop.
 */
class IsolateObjectCollector {
 public:
  explicit IsolateObjectCollector(IsolateManager* isolate_manager);
  ~IsolateObjectCollector();

  IsolateObjectCollector(const IsolateObjectCollector&) = delete;
  auto operator=(const IsolateObjectCollector&) -> IsolateObjectCollector& =
                                                       delete;
  IsolateObjectCollector(IsolateObjectCollector&&) = delete;
  auto operator=(IsolateObjectCollector&& other) -> IsolateObjectCollector& =
                                                        delete;

  void Collect(v8::Global<v8::Value> global);

 private:
  void EnqueueCollectionBatchLocked();
  void DoCollection();

  IsolateManager* isolate_manager_;
  std::mutex mutex_;
  std::vector<v8::Global<v8::Value>> garbage_;
  std::condition_variable collection_done_cv_;
  bool is_collecting_;
};

}  // namespace MiniRacer

#endif  // INCLUDE_MINI_RACER_ISOLATE_OBJECT_COLLECTOR_H
