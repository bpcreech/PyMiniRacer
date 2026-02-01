#ifndef INCLUDE_MINI_RACER_CONTEXT_H
#define INCLUDE_MINI_RACER_CONTEXT_H

#include <v8-platform.h>
#include <cstddef>
#include <cstdint>
#include <string_view>
#include "callback.h"
#include "cancelable_task_runner.h"
#include "code_evaluator.h"
#include "heap_reporter.h"
#include "isolate_manager.h"
#include "isolate_memory_monitor.h"
#include "js_callback_maker.h"
#include "object_manipulator.h"
#include "value.h"

namespace MiniRacer {

class ValueHandleConverter;

class Context {
 public:
  explicit Context(v8::Platform* platform, RawCallback callback);
  ~Context();

  Context(const Context&) = delete;
  auto operator=(const Context&) -> Context& = delete;
  Context(Context&&) = delete;
  auto operator=(Context&& other) -> Context& = delete;

  void SetHardMemoryLimit(size_t limit);
  void SetSoftMemoryLimit(size_t limit);

  [[nodiscard]] auto IsSoftMemoryLimitReached() const -> bool;
  [[nodiscard]] auto IsHardMemoryLimitReached() const -> bool;
  void ApplyLowMemoryNotification();

  void FreeValue(ValueHandle* val);
  auto AllocInt(int64_t val, ValueTypes type) -> ValueHandle*;
  auto AllocDouble(double val, ValueTypes type) -> ValueHandle*;
  auto AllocString(std::string_view val, ValueTypes type) -> ValueHandle*;
  void CancelTask(uint64_t task_id);
  auto HeapSnapshot() -> ValueHandle*;
  auto HeapStats() -> ValueHandle*;
  auto Eval(ValueHandle* code_handle,

            uint64_t callback_id) -> uint64_t;
  auto MakeJSCallback(uint64_t callback_id) -> ValueHandle*;
  auto GetIdentityHash(ValueHandle* obj_handle) -> ValueHandle*;
  auto GetOwnPropertyNames(ValueHandle* obj_handle) -> ValueHandle*;
  auto GetObjectItem(ValueHandle* obj_handle, ValueHandle* key_handle)
      -> ValueHandle*;
  auto SetObjectItem(ValueHandle* obj_handle,
                     ValueHandle* key_handle,
                     ValueHandle* val_handle) -> ValueHandle*;
  auto DelObjectItem(ValueHandle* obj_handle, ValueHandle* key_handle)
      -> ValueHandle*;
  auto SpliceArray(ValueHandle* obj_handle,
                   int32_t start,
                   int32_t delete_count,
                   ValueHandle* new_val_handle) -> ValueHandle*;
  auto ArrayPush(ValueHandle* obj_handle, ValueHandle* new_val_handle)
      -> ValueHandle*;
  auto CallFunction(ValueHandle* func_handle,
                    ValueHandle* this_handle,
                    ValueHandle* argv_handle,
                    uint64_t callback_id) -> uint64_t;
  auto ValueCount() -> size_t;

 private:
  template <typename Runnable>
  auto RunTask(Runnable runnable, uint64_t callback_id) -> uint64_t;

  auto MakeHandleError(const char* err_msg) -> ValueHandle*;

  RawCallback callback_;
  IsolateManager isolate_manager_;
  IsolateMemoryMonitor isolate_memory_monitor_;
  ValueFactory val_factory_;
  ValueRegistry val_registry_;
  JSCallbackMaker js_callback_maker_;
  CodeEvaluator code_evaluator_;
  HeapReporter heap_reporter_;
  ObjectManipulator object_manipulator_;
  CancelableTaskManager cancelable_task_manager_;
};

inline void Context::SetHardMemoryLimit(size_t limit) {
  isolate_memory_monitor_.SetHardMemoryLimit(limit);
}

inline void Context::SetSoftMemoryLimit(size_t limit) {
  isolate_memory_monitor_.SetSoftMemoryLimit(limit);
}

inline auto Context::IsSoftMemoryLimitReached() const -> bool {
  return isolate_memory_monitor_.IsSoftMemoryLimitReached();
}

inline auto Context::IsHardMemoryLimitReached() const -> bool {
  return isolate_memory_monitor_.IsHardMemoryLimitReached();
}

inline void Context::ApplyLowMemoryNotification() {
  isolate_memory_monitor_.ApplyLowMemoryNotification();
}

}  // namespace MiniRacer

#endif  // INCLUDE_MINI_RACER_CONTEXT_H
