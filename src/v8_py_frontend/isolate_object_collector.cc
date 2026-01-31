#include "isolate_object_collector.h"
#include <v8-isolate.h>
#include <functional>
#include <mutex>
#include <tuple>
#include <utility>
#include <vector>
#include "isolate_manager.h"

namespace MiniRacer {

IsolateObjectCollector::IsolateObjectCollector(IsolateManager* isolate_manager)
    : isolate_manager_(isolate_manager), is_collecting_(false) {}

IsolateObjectCollector::~IsolateObjectCollector() {
  std::unique_lock<std::mutex> lock(mutex_);
  collection_done_cv_.wait(lock, [this] { return !is_collecting_; });
}

void IsolateObjectCollector::EnqueueCollectionBatchLocked() {
  is_collecting_ = true;

  std::ignore = isolate_manager_->Run([this](v8::Isolate*) { DoCollection(); });
}

void IsolateObjectCollector::DoCollection() {
  std::vector<v8::Global<v8::Value>> batch;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    batch = std::exchange(garbage_, {});
  }

  batch.clear();

  const std::lock_guard<std::mutex> lock(mutex_);
  if (garbage_.empty()) {
    is_collecting_ = false;
    collection_done_cv_.notify_all();
    return;
  }

  EnqueueCollectionBatchLocked();
}

void IsolateObjectCollector::Collect(v8::Global<v8::Value> global) {
  const std::lock_guard<std::mutex> lock(mutex_);

  garbage_.push_back(std::move(global));

  if (is_collecting_) {
    // There is already a collection in progress.
    return;
  }

  EnqueueCollectionBatchLocked();
}
}  // end namespace MiniRacer
