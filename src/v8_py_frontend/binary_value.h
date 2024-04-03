#ifndef BINARY_VALUE_H
#define BINARY_VALUE_H

#include <v8-array-buffer.h>
#include <v8-context.h>
#include <v8-local-handle.h>
#include <v8-message.h>
#include <v8-persistent-handle.h>
#include <v8-value.h>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string_view>
#include <unordered_map>
#include <vector>
#include "gsl_stub.h"
#include "isolate_manager.h"

namespace MiniRacer {

enum BinaryTypes : uint8_t {
  type_invalid = 0,
  type_null = 1,
  type_bool = 2,
  type_integer = 3,
  type_double = 4,
  type_str_utf8 = 5,
  type_array = 6,
  // type_hash      =   7,  // deprecated
  type_date = 8,
  type_symbol = 9,
  type_object = 10,
  type_undefined = 11,

  type_function = 100,
  type_shared_array_buffer = 101,
  type_array_buffer = 102,
  type_promise = 103,

  type_execute_exception = 200,
  type_parse_exception = 201,
  type_oom_exception = 202,
  type_timeout_exception = 203,
  type_terminated_exception = 204,
  type_value_exception = 205,
  type_key_exception = 206,
};

// NOLINTBEGIN(misc-non-private-member-variables-in-classes)
// NOLINTBEGIN(cppcoreguidelines-owning-memory)
// NOLINTBEGIN(cppcoreguidelines-pro-type-member-init)
// NOLINTBEGIN(hicpp-member-init)
/** A simplified structure designed for sharing data with non-C++ code over a C
 * foreign function API (e.g., Python ctypes). This object directly provides
 * values for some simple types (e.g., numbers and strings), and also acts as a
 * handle for the non-C++ code to manage opaque data via our APIs. */
struct BinaryValueHandle {
  union {
    char* bytes;
    int64_t int_val;
    double double_val;
  };
  size_t len;
  BinaryTypes type = type_invalid;
} __attribute__((packed));
// NOLINTEND(hicpp-member-init)
// NOLINTEND(cppcoreguidelines-pro-type-member-init)
// NOLINTEND(cppcoreguidelines-owning-memory)
// NOLINTEND(misc-non-private-member-variables-in-classes)

class IsolateObjectDeleter {
 public:
  IsolateObjectDeleter();
  explicit IsolateObjectDeleter(IsolateManager* isolate_manager);

  template <typename T>
  void operator()(T* handle) const;

 private:
  IsolateManager* isolate_manager_;
};

class BinaryValue {
 public:
  BinaryValue(IsolateObjectDeleter isolate_object_deleter,
              std::string_view val,
              BinaryTypes result_type);
  BinaryValue(IsolateObjectDeleter isolate_object_deleter, bool val);
  BinaryValue(IsolateObjectDeleter isolate_object_deleter,
              int64_t val,
              BinaryTypes result_type);
  BinaryValue(IsolateObjectDeleter isolate_object_deleter,
              double val,
              BinaryTypes result_type);
  BinaryValue(IsolateObjectDeleter isolate_object_deleter,
              v8::Local<v8::Context> context,
              v8::Local<v8::Value> value);
  BinaryValue(IsolateObjectDeleter isolate_object_deleter,
              v8::Local<v8::Context> context,
              v8::Local<v8::Message> message,
              v8::Local<v8::Value> exception_obj,
              BinaryTypes result_type);

  using Ptr = std::shared_ptr<BinaryValue>;

  auto ToValue(v8::Local<v8::Context> context) -> v8::Local<v8::Value>;
  auto GetHandle() -> BinaryValueHandle*;

 private:
  void SavePersistentHandle(v8::Isolate* isolate, v8::Local<v8::Value> value);
  void CreateBackingStoreRef(v8::Local<v8::Value> value);

  IsolateObjectDeleter isolate_object_deleter_;
  BinaryValueHandle handle_;
  std::vector<char> msg_;
  std::unique_ptr<v8::Persistent<v8::Value>, IsolateObjectDeleter>
      persistent_handle_;
  std::unique_ptr<std::shared_ptr<v8::BackingStore>, IsolateObjectDeleter>
      backing_store_;
};

class BinaryValueFactory {
 public:
  explicit BinaryValueFactory(IsolateManager* isolate_manager);

  auto FromHandle(BinaryValueHandle* handle) -> BinaryValue::Ptr;
  void Free(BinaryValueHandle* handle);
  auto Count() -> size_t;

  template <typename... Params>
  auto New(Params&&... params) -> BinaryValue::Ptr;

 private:
  IsolateManager* isolate_manager_;
  std::mutex mutex_;
  std::unordered_map<BinaryValueHandle*, std::shared_ptr<BinaryValue>> values_;
};

template <typename T>
void IsolateObjectDeleter::operator()(gsl::owner<T*> handle) const {
  // We don't generally own the isolate lock (i.e., aren't running from the
  // IsolateManager's message loop) here. From the V8 documentation, it's not
  // clear if we can safely free v8 objects like a v8::Persistent handle or
  // decrement the ref count of a std::shared_ptr<v8::BackingStore> (which may
  // free the BackingStore) without the lock. As a rule, messing with
  // Isolate-owned objects without holding the Isolate lock is not safe, and
  // there is no documentation indicating methods like
  // v8::Persistent::~Persistent are exempt from this rule. So let's have the
  // message loop handle the deletion.

  // Note also that we don't wait on the deletion here. This method may be
  // called by Python, as a result of callbacks from the C++ side of MiniRacer.
  // Those callbacks originate from the IsolateManager message loop itself. If
  // we were to wait on this *new* task we're adding to the message loop, we
  // would deadlock.
  isolate_manager_->Run(
      [handle](v8::Isolate* /*isolate*/) mutable { delete handle; });
}

template <typename... Params>
inline auto BinaryValueFactory::New(Params&&... params) -> BinaryValue::Ptr {
  auto ptr = std::make_shared<BinaryValue>(
      IsolateObjectDeleter(isolate_manager_), std::forward<Params>(params)...);

  {
    // Track all created binary values to relieve Python of the duty of garbage
    // collecting them in the correct order relative to the MiniRacer::Context:
    const std::lock_guard<std::mutex> lock(mutex_);
    values_[ptr->GetHandle()] = ptr;
  }

  return ptr;
}

}  // namespace MiniRacer

#endif  // BINARY_VALUE_H
