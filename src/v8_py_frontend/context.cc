#include "context.h"
#include <v8-initialization.h>
#include <v8-platform.h>
#include <cstddef>
#include <cstdint>
#include <string_view>
#include <utility>
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

Context::Context(v8::Platform* platform, RawCallback callback)
    : callback_(callback),
      isolate_manager_(platform),
      isolate_memory_monitor_(&isolate_manager_),
      val_factory_(&isolate_manager_),
      js_callback_maker_(&isolate_manager_,
                         &val_factory_,
                         &val_registry_,
                         callback_),
      code_evaluator_(&isolate_manager_,
                      &val_factory_,
                      &isolate_memory_monitor_),
      heap_reporter_(&isolate_manager_, &val_factory_),
      object_manipulator_(&isolate_manager_, &val_factory_),
      cancelable_task_manager_(&isolate_manager_) {}

Context::~Context() {
  // We stop JavaScript from running, but keep running the event loop, because
  // cleanup tasks still use the event loop:
  isolate_manager_.StopJavaScript();
}

auto Context::MakeJSCallback(uint64_t callback_id) -> ValueHandle* {
  return val_registry_.Remember(isolate_manager_
                                    .Schedule([this, callback_id]() {
                                      return js_callback_maker_.MakeJSCallback(
                                          callback_id);
                                    })
                                    .get());
}

template <typename Runnable>
auto Context::RunTask(Runnable runnable, uint64_t callback_id) -> uint64_t {
  // Start an async task!
  return cancelable_task_manager_.Schedule(
      /*runnable=*/
      std::move(runnable),
      /*on_completed=*/
      [this, callback_id](ValueHandle* val) { callback_(callback_id, val); },
      /*on_canceled=*/
      [this, callback_id](ValueHandle* val) {
        if (val == nullptr) {
          callback_(callback_id,
                    val_registry_.Remember(val_factory_.NewFromString(
                        "execution terminated", type_terminated_exception)));
          return;
        }

        // This may happen if the task was mid-execution when we interrupted
        // it.
        callback_(callback_id, val);
      });
}

auto Context::MakeHandleError(const char* err_msg) -> ValueHandle* {
  return val_registry_.Remember(
      val_factory_.NewFromString(err_msg, type_value_exception));
}

auto Context::Eval(ValueHandle* code_handle, uint64_t callback_id) -> uint64_t {
  return RunTask(
      [this, code_handle]() {
        auto* code_value = val_registry_.FromHandle(code_handle);
        if (code_value == nullptr) {
          return MakeHandleError("Bad handle: code");
        }

        return val_registry_.Remember(code_evaluator_.Eval(code_value));
      },
      callback_id);
}

void Context::CancelTask(uint64_t task_id) {
  cancelable_task_manager_.Cancel(task_id);
}

auto Context::HeapSnapshot() -> ValueHandle* {
  return isolate_manager_
      .Schedule([this]() mutable {
        return val_registry_.Remember(heap_reporter_.HeapSnapshot());
      })
      .get();
}

auto Context::HeapStats() -> ValueHandle* {
  return isolate_manager_
      .Schedule([this]() mutable {
        return val_registry_.Remember(heap_reporter_.HeapStats());
      })
      .get();
}

auto Context::GetIdentityHash(ValueHandle* obj_handle) -> ValueHandle* {
  return isolate_manager_
      .Schedule([this, obj_handle]() {
        auto* obj_value = val_registry_.FromHandle(obj_handle);
        if (obj_value == nullptr) {
          return MakeHandleError("Bad handle: obj");
        }

        return val_registry_.Remember(
            object_manipulator_.GetIdentityHash(obj_value));
      })
      .get();
}

auto Context::GetOwnPropertyNames(ValueHandle* obj_handle) -> ValueHandle* {
  return isolate_manager_
      .Schedule([this, obj_handle]() {
        auto* obj_value = val_registry_.FromHandle(obj_handle);
        if (obj_value == nullptr) {
          return MakeHandleError("Bad handle: obj");
        }

        return val_registry_.Remember(
            object_manipulator_.GetOwnPropertyNames(obj_value));
      })
      .get();
}

auto Context::GetObjectItem(ValueHandle* obj_handle, ValueHandle* key_handle)
    -> ValueHandle* {
  return isolate_manager_
      .Schedule([this, obj_handle, key_handle]() mutable {
        auto* obj_value = val_registry_.FromHandle(obj_handle);
        if (obj_value == nullptr) {
          return MakeHandleError("Bad handle: obj");
        }

        auto* key_value = val_registry_.FromHandle(key_handle);
        if (key_value == nullptr) {
          return MakeHandleError("Bad handle: key");
        }

        return val_registry_.Remember(
            object_manipulator_.Get(obj_value, key_value));
      })
      .get();
}

auto Context::SetObjectItem(ValueHandle* obj_handle,
                            ValueHandle* key_handle,
                            ValueHandle* val_handle) -> ValueHandle* {
  return isolate_manager_
      .Schedule([this, obj_handle, key_handle, val_handle]() mutable {
        auto* obj_value = val_registry_.FromHandle(obj_handle);
        if (obj_value == nullptr) {
          return MakeHandleError("Bad handle: obj");
        }

        auto* key_value = val_registry_.FromHandle(key_handle);
        if (key_value == nullptr) {
          return MakeHandleError("Bad handle: key");
        }

        auto* val_value = val_registry_.FromHandle(val_handle);
        if (val_value == nullptr) {
          return MakeHandleError("Bad handle: val");
        }

        return val_registry_.Remember(
            object_manipulator_.Set(obj_value, key_value, val_value));
      })
      .get();
}

auto Context::DelObjectItem(ValueHandle* obj_handle, ValueHandle* key_handle)
    -> ValueHandle* {
  return isolate_manager_
      .Schedule([this, obj_handle, key_handle]() mutable {
        auto* obj_value = val_registry_.FromHandle(obj_handle);
        if (obj_value == nullptr) {
          return MakeHandleError("Bad handle: obj");
        }

        auto* key_value = val_registry_.FromHandle(key_handle);
        if (key_value == nullptr) {
          return MakeHandleError("Bad handle: key");
        }

        return val_registry_.Remember(
            object_manipulator_.Del(obj_value, key_value));
      })
      .get();
}

auto Context::SpliceArray(ValueHandle* obj_handle,
                          int32_t start,
                          int32_t delete_count,
                          ValueHandle* new_val_handle) -> ValueHandle* {
  return isolate_manager_
      .Schedule([this, obj_handle, start, delete_count, new_val_handle]() {
        auto* obj_value = val_registry_.FromHandle(obj_handle);
        if (obj_value == nullptr) {
          return MakeHandleError("Bad handle: obj");
        }

        Value* new_val_value = nullptr;
        if (new_val_handle != nullptr) {
          new_val_value = val_registry_.FromHandle(new_val_handle);
          if (new_val_value == nullptr) {
            return MakeHandleError("Bad handle: new_value");
          }
        }

        return val_registry_.Remember(object_manipulator_.Splice(
            obj_value, start, delete_count, new_val_value));
      })
      .get();
}

auto Context::ArrayPush(ValueHandle* obj_handle, ValueHandle* new_val_handle)
    -> ValueHandle* {
  return isolate_manager_
      .Schedule([this, obj_handle, new_val_handle]() {
        auto* obj_value = val_registry_.FromHandle(obj_handle);
        if (obj_value == nullptr) {
          return MakeHandleError("Bad handle: obj");
        }

        auto* new_val_value = val_registry_.FromHandle(new_val_handle);
        if (new_val_value == nullptr) {
          return MakeHandleError("Bad handle: new_val");
        }

        return val_registry_.Remember(
            object_manipulator_.Push(obj_value, new_val_value));
      })
      .get();
}

void Context::FreeValue(ValueHandle* val) {
  isolate_manager_.Schedule([this, val]() { val_registry_.Forget(val); }).get();
}

auto Context::AllocInt(int64_t val, ValueTypes type) -> ValueHandle* {
  return isolate_manager_
      .Schedule([this, val, type]() {
        return val_registry_.Remember(val_factory_.NewFromInt(val, type));
      })
      .get();
}

auto Context::AllocDouble(double val, ValueTypes type) -> ValueHandle* {
  return isolate_manager_
      .Schedule([this, val, type]() {
        return val_registry_.Remember(val_factory_.NewFromDouble(val, type));
      })
      .get();
}

auto Context::AllocString(std::string_view val, ValueTypes type)
    -> ValueHandle* {
  return isolate_manager_
      .Schedule([this, val, type]() {
        return val_registry_.Remember(val_factory_.NewFromString(val, type));
      })
      .get();
}

auto Context::CallFunction(ValueHandle* func_handle,
                           ValueHandle* this_handle,
                           ValueHandle* argv_handle,
                           uint64_t callback_id) -> uint64_t {
  return RunTask(
      [this, func_handle, this_handle, argv_handle]() {
        auto* func_value = val_registry_.FromHandle(func_handle);
        if (func_value == nullptr) {
          return MakeHandleError("Bad handle: func");
        }

        auto* this_value = val_registry_.FromHandle(this_handle);
        if (this_value == nullptr) {
          return MakeHandleError("Bad handle: this");
        }

        auto* argv_value = val_registry_.FromHandle(argv_handle);
        if (argv_value == nullptr) {
          return MakeHandleError("Bad handle: argv");
        }

        return val_registry_.Remember(
            object_manipulator_.Call(func_value, this_value, argv_value));
      },
      callback_id);
}

auto Context::ValueCount() -> size_t {
  return isolate_manager_.Schedule([this]() { return val_registry_.Count(); })
      .get();
}

}  // end namespace MiniRacer
