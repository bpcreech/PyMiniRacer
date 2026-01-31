#include "context.h"
#include <v8-initialization.h>
#include <v8-local-handle.h>
#include <v8-locker.h>
#include <v8-persistent-handle.h>
#include <v8-platform.h>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <utility>
#include "callback.h"
#include "cancelable_task_runner.h"
#include "code_evaluator.h"
#include "context_holder.h"
#include "heap_reporter.h"
#include "isolate_manager.h"
#include "isolate_memory_monitor.h"
#include "js_callback_maker.h"
#include "object_manipulator.h"
#include "value.h"

namespace MiniRacer {

Context::Context(v8::Platform* platform, RawCallback callback)
    : isolate_manager_(platform),
      isolate_object_collector_(&isolate_manager_),
      isolate_memory_monitor_(&isolate_manager_),
      val_factory_(isolate_manager_.Get(), &isolate_object_collector_),
      callback_([this, callback](uint64_t callback_id, Value::Ptr val) {
        callback(callback_id, val_registry_.Remember(std::move(val)));
      }),
      context_holder_(&isolate_manager_),
      js_callback_maker_(&context_holder_, &val_factory_, callback_),
      code_evaluator_(&context_holder_,
                      &val_factory_,
                      &isolate_memory_monitor_),
      heap_reporter_(&val_factory_),
      object_manipulator_(&context_holder_, &val_factory_),
      cancelable_task_manager_(&isolate_manager_) {}

Context::~Context() {
  // We stop JavaScript from running, but keep running the event loop, because
  // cleanup tasks still use the event loop:
  isolate_manager_.StopJavaScript();
}

auto Context::MakeJSCallback(uint64_t callback_id) -> ValueHandle* {
  return val_registry_.Remember(
      isolate_manager_
          .Run([this, callback_id](v8::Isolate* isolate) {
            return js_callback_maker_.MakeJSCallback(isolate, callback_id);
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
      [this, callback_id](const Value::Ptr& val) {
        callback_(callback_id, val);
      },
      /*on_canceled=*/
      [this, callback_id](const Value::Ptr& /*val*/) {
        auto err =
            val_factory_.New("execution terminated", type_terminated_exception);
        callback_(callback_id, err);
      });
}

auto Context::MakeHandleConverter(ValueHandle* handle,
                                  const char* err_msg) -> ValueHandleConverter {
  return {&val_factory_, &val_registry_, handle, err_msg};
}

ValueHandleConverter::ValueHandleConverter(ValueFactory* val_factory,
                                           ValueRegistry* val_registry,
                                           ValueHandle* handle,
                                           const char* err_msg)
    : val_registry_(val_registry),
      ptr_(val_registry->FromHandle(handle)),
      err_([&val_factory, err_msg, this]() {
        if (ptr_) {
          return Value::Ptr();
        }

        return val_factory->New(err_msg, type_value_exception);
      }()) {}

ValueHandleConverter::operator bool() const {
  return static_cast<bool>(ptr_);
}

auto ValueHandleConverter::GetErrorPtr() -> Value::Ptr {
  return err_;
}

auto ValueHandleConverter::GetErrorHandle() -> ValueHandle* {
  return val_registry_->Remember(err_);
}

auto ValueHandleConverter::GetPtr() -> Value::Ptr {
  return ptr_;
}

auto Context::Eval(ValueHandle* code_handle, uint64_t callback_id) -> uint64_t {
  auto code_hc = MakeHandleConverter(code_handle, "Bad handle: code");
  if (!code_hc) {
    return RunTask(
        [err = code_hc.GetErrorPtr()](v8::Isolate* /*isolate*/) { return err; },
        callback_id);
  }

  return RunTask(
      [code_ptr = code_hc.GetPtr(), this](v8::Isolate* isolate) {
        return code_evaluator_.Eval(isolate, code_ptr.get());
      },
      callback_id);
}

void Context::CancelTask(uint64_t task_id) {
  cancelable_task_manager_.Cancel(task_id);
}

auto Context::HeapSnapshot() -> ValueHandle* {
  return val_registry_.Remember(isolate_manager_
                                    .Run([this](v8::Isolate* isolate) mutable {
                                      return heap_reporter_.HeapSnapshot(
                                          isolate);
                                    })
                                    .get());
}

auto Context::HeapStats() -> ValueHandle* {
  return val_registry_.Remember(isolate_manager_
                                    .Run([this](v8::Isolate* isolate) mutable {
                                      return heap_reporter_.HeapStats(isolate);
                                    })
                                    .get());
}

auto Context::GetIdentityHash(ValueHandle* obj_handle) -> ValueHandle* {
  auto obj_hc = MakeHandleConverter(obj_handle, "Bad handle: obj");
  if (!obj_hc) {
    return obj_hc.GetErrorHandle();
  }

  return val_registry_.Remember(
      isolate_manager_
          .Run([this, obj_ptr = obj_hc.GetPtr()](v8::Isolate* isolate) {
            return object_manipulator_.GetIdentityHash(isolate, obj_ptr.get());
          })
          .get());
}

auto Context::GetOwnPropertyNames(ValueHandle* obj_handle) -> ValueHandle* {
  auto obj_hc = MakeHandleConverter(obj_handle, "Bad handle: obj");
  if (!obj_hc) {
    return obj_hc.GetErrorHandle();
  }

  return val_registry_.Remember(
      isolate_manager_
          .Run([this, obj_ptr = obj_hc.GetPtr()](v8::Isolate* isolate) {
            return object_manipulator_.GetOwnPropertyNames(isolate,
                                                           obj_ptr.get());
          })
          .get());
}

auto Context::GetObjectItem(ValueHandle* obj_handle,
                            ValueHandle* key_handle) -> ValueHandle* {
  auto obj_hc = MakeHandleConverter(obj_handle, "Bad handle: obj");
  if (!obj_hc) {
    return obj_hc.GetErrorHandle();
  }

  auto key_hc = MakeHandleConverter(key_handle, "Bad handle: key");
  if (!key_hc) {
    return key_hc.GetErrorHandle();
  }

  return val_registry_.Remember(
      isolate_manager_
          .Run([this, obj_ptr = obj_hc.GetPtr(),
                key_ptr = key_hc.GetPtr()](v8::Isolate* isolate) mutable {
            return object_manipulator_.Get(isolate, obj_ptr.get(),
                                           key_ptr.get());
          })
          .get());
}

auto Context::SetObjectItem(ValueHandle* obj_handle,
                            ValueHandle* key_handle,
                            ValueHandle* val_handle) -> ValueHandle* {
  auto obj_hc = MakeHandleConverter(obj_handle, "Bad handle: obj");
  if (!obj_hc) {
    return obj_hc.GetErrorHandle();
  }

  auto key_hc = MakeHandleConverter(key_handle, "Bad handle: key");
  if (!key_hc) {
    return key_hc.GetErrorHandle();
  }

  auto val_hc = MakeHandleConverter(val_handle, "Bad handle: val");
  if (!val_hc) {
    return val_hc.GetErrorHandle();
  }

  return val_registry_.Remember(
      isolate_manager_
          .Run([this, obj_ptr = obj_hc.GetPtr(), key_ptr = key_hc.GetPtr(),
                val_ptr = val_hc.GetPtr()](v8::Isolate* isolate) mutable {
            return object_manipulator_.Set(isolate, obj_ptr.get(),
                                           key_ptr.get(), val_ptr.get());
          })
          .get());
}

auto Context::DelObjectItem(ValueHandle* obj_handle,
                            ValueHandle* key_handle) -> ValueHandle* {
  auto obj_hc = MakeHandleConverter(obj_handle, "Bad handle: obj");
  if (!obj_hc) {
    return obj_hc.GetErrorHandle();
  }

  auto key_hc = MakeHandleConverter(key_handle, "Bad handle: key");
  if (!key_hc) {
    return key_hc.GetErrorHandle();
  }

  return val_registry_.Remember(
      isolate_manager_
          .Run([this, obj_ptr = obj_hc.GetPtr(),
                key_ptr = key_hc.GetPtr()](v8::Isolate* isolate) mutable {
            return object_manipulator_.Del(isolate, obj_ptr.get(),
                                           key_ptr.get());
          })
          .get());
}

auto Context::SpliceArray(ValueHandle* obj_handle,
                          int32_t start,
                          int32_t delete_count,
                          ValueHandle* new_val_handle) -> ValueHandle* {
  auto obj_hc = MakeHandleConverter(obj_handle, "Bad handle: obj");
  if (!obj_hc) {
    return obj_hc.GetErrorHandle();
  }

  Value::Ptr new_val_ptr;
  if (new_val_handle != nullptr) {
    auto new_val_hc =
        MakeHandleConverter(new_val_handle, "Bad handle: new_val");
    if (!new_val_hc) {
      return new_val_hc.GetErrorHandle();
    }
    new_val_ptr = new_val_hc.GetPtr();
  }

  return val_registry_.Remember(
      isolate_manager_
          .Run([this, obj_ptr = obj_hc.GetPtr(), start, delete_count,
                new_val_ptr](v8::Isolate* isolate) {
            return object_manipulator_.Splice(isolate, obj_ptr.get(), start,
                                              delete_count, new_val_ptr.get());
          })
          .get());
}

auto Context::ArrayPush(ValueHandle* obj_handle,
                        ValueHandle* new_val_handle) -> ValueHandle* {
  auto obj_hc = MakeHandleConverter(obj_handle, "Bad handle: obj");
  if (!obj_hc) {
    return obj_hc.GetErrorHandle();
  }

  auto new_val_hc = MakeHandleConverter(new_val_handle, "Bad handle: new_val");
  if (!new_val_hc) {
    return new_val_hc.GetErrorHandle();
  }

  return val_registry_.Remember(
      isolate_manager_
          .Run([this, obj_ptr = obj_hc.GetPtr(),
                new_val_ptr = new_val_hc.GetPtr()](v8::Isolate* isolate) {
            return object_manipulator_.Push(isolate, obj_ptr.get(),
                                            new_val_ptr.get());
          })
          .get());
}

void Context::FreeValue(ValueHandle* val) {
  val_registry_.Forget(val);
}

auto Context::CallFunction(ValueHandle* func_handle,
                           ValueHandle* this_handle,
                           ValueHandle* argv_handle,
                           uint64_t callback_id) -> uint64_t {
  auto func_hc = MakeHandleConverter(func_handle, "Bad handle: func");
  if (!func_hc) {
    return RunTask(
        [err = func_hc.GetErrorPtr()](v8::Isolate* /*isolate*/) { return err; },
        callback_id);
  }

  auto this_hc = MakeHandleConverter(this_handle, "Bad handle: this");
  if (!this_hc) {
    return RunTask(
        [err = this_hc.GetErrorPtr()](v8::Isolate* /*isolate*/) { return err; },
        callback_id);
  }

  auto argv_hc = MakeHandleConverter(argv_handle, "Bad handle: argv");
  if (!argv_hc) {
    return RunTask(
        [err = argv_hc.GetErrorPtr()](v8::Isolate* /*isolate*/) { return err; },
        callback_id);
  }

  return RunTask(
      [this, func_ptr = func_hc.GetPtr(), this_ptr = this_hc.GetPtr(),
       argv_ptr = argv_hc.GetPtr()](v8::Isolate* isolate) {
        return object_manipulator_.Call(isolate, func_ptr.get(), this_ptr.get(),
                                        argv_ptr.get());
      },
      callback_id);
}

auto Context::ValueCount() -> size_t {
  return val_registry_.Count();
}

}  // end namespace MiniRacer
