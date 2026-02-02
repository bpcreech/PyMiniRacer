#include "exports.h"
#include <v8-initialization.h>
#include <v8-version-string.h>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include "callback.h"
#include "context.h"
#include "context_factory.h"
#include "value.h"

namespace {
auto GetContext(uint64_t context_id) -> std::shared_ptr<MiniRacer::Context> {
  auto* context_factory = MiniRacer::ContextFactory::Get();
  if (context_factory == nullptr) {
    return nullptr;
  }
  return context_factory->GetContext(context_id);
}
}  // end anonymous namespace

// This lint check wants us to make classes to encompass parameters, which
// isn't very helpful in a low-level cross-language API (we'd be just as
// likely, if not more likely, to mess up the Python representation of any
// struct created to encompass these parameters):
// NOLINTBEGIN(bugprone-easily-swappable-parameters)

LIB_EXPORT auto mr_eval(uint64_t context_id,
                        MiniRacer::ValueHandle* code_handle,
                        uint64_t callback_id) -> uint64_t {
  auto context = GetContext(context_id);
  if (!context) {
    return 0;
  }
  return context->Eval(code_handle, callback_id);
}

LIB_EXPORT void mr_init_v8(const char* v8_flags, const char* icu_path) {
  MiniRacer::ContextFactory::Init(v8_flags, icu_path);
}

LIB_EXPORT auto mr_init_context(MiniRacer::RawCallback callback) -> uint64_t {
  auto* context_factory = MiniRacer::ContextFactory::Get();
  if (context_factory == nullptr) {
    return 0;
  }
  return context_factory->MakeContext(callback);
}

LIB_EXPORT void mr_free_context(uint64_t context_id) {
  auto* context_factory = MiniRacer::ContextFactory::Get();
  if (context_factory == nullptr) {
    return;
  }
  context_factory->FreeContext(context_id);
}

LIB_EXPORT auto mr_context_count() -> size_t {
  auto* context_factory = MiniRacer::ContextFactory::Get();
  if (context_factory == nullptr) {
    return std::numeric_limits<size_t>::max();
  }
  return context_factory->Count();
}

LIB_EXPORT void mr_free_value(uint64_t context_id,
                              MiniRacer::ValueHandle* val_handle) {
  auto context = GetContext(context_id);
  if (!context) {
    return;
  }
  context->FreeValue(val_handle);
}

LIB_EXPORT auto mr_alloc_int_val(uint64_t context_id,
                                 int64_t val,
                                 MiniRacer::ValueTypes type)
    -> MiniRacer::ValueHandle* {
  auto context = GetContext(context_id);
  if (!context) {
    return nullptr;
  }
  return context->AllocInt(val, type);
}

LIB_EXPORT auto mr_alloc_double_val(uint64_t context_id,
                                    double val,
                                    MiniRacer::ValueTypes type)
    -> MiniRacer::ValueHandle* {
  auto context = GetContext(context_id);
  if (!context) {
    return nullptr;
  }
  return context->AllocDouble(val, type);
}

LIB_EXPORT auto mr_alloc_string_val(uint64_t context_id,
                                    char* val,
                                    uint64_t len,
                                    MiniRacer::ValueTypes type)
    -> MiniRacer::ValueHandle* {
  auto context = GetContext(context_id);
  if (!context) {
    return nullptr;
  }
  return context->AllocString(std::string_view(val, len), type);
}

LIB_EXPORT void mr_cancel_task(uint64_t context_id, uint64_t task_id) {
  auto context = GetContext(context_id);
  if (!context) {
    return;
  }
  context->CancelTask(task_id);
}

LIB_EXPORT auto mr_heap_stats(uint64_t context_id) -> MiniRacer::ValueHandle* {
  auto context = GetContext(context_id);
  if (!context) {
    return nullptr;
  }
  return context->HeapStats();
}

LIB_EXPORT void mr_set_hard_memory_limit(uint64_t context_id, size_t limit) {
  auto context = GetContext(context_id);
  if (!context) {
    return;
  }
  context->SetHardMemoryLimit(limit);
}

LIB_EXPORT void mr_set_soft_memory_limit(uint64_t context_id, size_t limit) {
  auto context = GetContext(context_id);
  if (!context) {
    return;
  }
  context->SetSoftMemoryLimit(limit);
}

LIB_EXPORT auto mr_hard_memory_limit_reached(uint64_t context_id) -> bool {
  auto context = GetContext(context_id);
  if (!context) {
    return false;
  }
  return context->IsHardMemoryLimitReached();
}

LIB_EXPORT auto mr_soft_memory_limit_reached(uint64_t context_id) -> bool {
  auto context = GetContext(context_id);
  if (!context) {
    return false;
  }
  return context->IsSoftMemoryLimitReached();
}

LIB_EXPORT void mr_low_memory_notification(uint64_t context_id) {
  auto context = GetContext(context_id);
  if (!context) {
    return;
  }
  context->ApplyLowMemoryNotification();
}

LIB_EXPORT auto mr_make_js_callback(uint64_t context_id, uint64_t callback_id)
    -> MiniRacer::ValueHandle* {
  auto context = GetContext(context_id);
  if (!context) {
    return nullptr;
  }
  return context->MakeJSCallback(callback_id);
}

LIB_EXPORT auto mr_v8_version() -> char const* {
  return V8_VERSION_STRING;
}

LIB_EXPORT auto mr_v8_is_using_sandbox() -> bool {
  return v8::V8::IsSandboxConfiguredSecurely();
}

LIB_EXPORT auto mr_get_identity_hash(uint64_t context_id,
                                     MiniRacer::ValueHandle* obj_handle)
    -> MiniRacer::ValueHandle* {
  auto context = GetContext(context_id);
  if (!context) {
    return nullptr;
  }
  return context->GetIdentityHash(obj_handle);
}

LIB_EXPORT auto mr_get_own_property_names(uint64_t context_id,
                                          MiniRacer::ValueHandle* obj_handle)
    -> MiniRacer::ValueHandle* {
  auto context = GetContext(context_id);
  if (!context) {
    return nullptr;
  }
  return context->GetOwnPropertyNames(obj_handle);
}

LIB_EXPORT auto mr_get_object_item(uint64_t context_id,
                                   MiniRacer::ValueHandle* obj_handle,
                                   MiniRacer::ValueHandle* key_handle)
    -> MiniRacer::ValueHandle* {
  auto context = GetContext(context_id);
  if (!context) {
    return nullptr;
  }
  return context->GetObjectItem(obj_handle, key_handle);
}

LIB_EXPORT auto mr_set_object_item(uint64_t context_id,
                                   MiniRacer::ValueHandle* obj_handle,
                                   MiniRacer::ValueHandle* key_handle,
                                   MiniRacer::ValueHandle* val_handle)
    -> MiniRacer::ValueHandle* {
  auto context = GetContext(context_id);
  if (!context) {
    return nullptr;
  }
  return context->SetObjectItem(obj_handle, key_handle, val_handle);
}

LIB_EXPORT auto mr_del_object_item(uint64_t context_id,
                                   MiniRacer::ValueHandle* obj_handle,
                                   MiniRacer::ValueHandle* key_handle)
    -> MiniRacer::ValueHandle* {
  auto context = GetContext(context_id);
  if (!context) {
    return nullptr;
  }
  return context->DelObjectItem(obj_handle, key_handle);
}

LIB_EXPORT auto mr_splice_array(uint64_t context_id,
                                MiniRacer::ValueHandle* array_handle,
                                int32_t start,
                                int32_t delete_count,
                                MiniRacer::ValueHandle* new_val_handle)
    -> MiniRacer::ValueHandle* {
  auto context = GetContext(context_id);
  if (!context) {
    return nullptr;
  }
  return context->SpliceArray(array_handle, start, delete_count,
                              new_val_handle);
}

LIB_EXPORT auto mr_array_push(uint64_t context_id,
                              MiniRacer::ValueHandle* array_handle,
                              MiniRacer::ValueHandle* new_val_handle)
    -> MiniRacer::ValueHandle* {
  auto context = GetContext(context_id);
  if (!context) {
    return nullptr;
  }
  return context->ArrayPush(array_handle, new_val_handle);
}

LIB_EXPORT auto mr_call_function(uint64_t context_id,
                                 MiniRacer::ValueHandle* func_handle,
                                 MiniRacer::ValueHandle* this_handle,
                                 MiniRacer::ValueHandle* argv_handle,
                                 uint64_t callback_id) -> uint64_t {
  auto context = GetContext(context_id);
  if (!context) {
    return 0;
  }
  return context->CallFunction(func_handle, this_handle, argv_handle,
                               callback_id);
}

LIB_EXPORT auto mr_heap_snapshot(uint64_t context_id)
    -> MiniRacer::ValueHandle* {
  auto context = GetContext(context_id);
  if (!context) {
    return nullptr;
  }
  return context->HeapSnapshot();
}

LIB_EXPORT auto mr_value_count(uint64_t context_id) -> size_t {
  auto context = GetContext(context_id);
  if (!context) {
    return 0;
  }
  return context->ValueCount();
}

// NOLINTEND(bugprone-easily-swappable-parameters)
