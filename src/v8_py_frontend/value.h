#ifndef INCLUDE_MINI_RACER_VALUE_H
#define INCLUDE_MINI_RACER_VALUE_H

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
#include <variant>
#include <vector>
#include "isolate_object_collector.h"

namespace MiniRacer {

enum ValueTypes : uint8_t {
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
struct ValueHandle {
  union {
    char* bytes;
    int64_t int_val;
    double double_val;
  };
  size_t len;
  ValueTypes type = type_invalid;
} __attribute__((packed));
// NOLINTEND(hicpp-member-init)
// NOLINTEND(cppcoreguidelines-pro-type-member-init)
// NOLINTEND(cppcoreguidelines-owning-memory)
// NOLINTEND(misc-non-private-member-variables-in-classes)

class Value {
 public:
  Value(v8::Isolate* isolate,
        IsolateObjectCollector* isolate_object_collector,
        std::string_view val,
        ValueTypes result_type);
  Value(v8::Isolate* isolate,
        IsolateObjectCollector* isolate_object_collector,
        bool val);
  Value(v8::Isolate* isolate,
        IsolateObjectCollector* isolate_object_collector,
        int64_t val,
        ValueTypes result_type);
  Value(v8::Isolate* isolate,
        IsolateObjectCollector* isolate_object_collector,
        double val,
        ValueTypes result_type);
  Value(v8::Isolate* isolate,
        IsolateObjectCollector* isolate_object_collector,
        v8::Local<v8::Context> context,
        v8::Local<v8::Value> value);
  Value(v8::Isolate* isolate,
        IsolateObjectCollector* isolate_object_collector,
        v8::Local<v8::Context> context,
        v8::Local<v8::Message> message,
        v8::Local<v8::Value> exception_obj,
        ValueTypes result_type);

  ~Value();

  Value(const Value& other) = delete;
  Value(Value&& other) noexcept = delete;
  auto operator=(const Value& other) -> Value& = delete;
  auto operator=(Value&& other) noexcept -> Value& = delete;

  using Ptr = std::shared_ptr<Value>;

  auto ToV8Value(v8::Isolate* isolate,
                 v8::Local<v8::Context> context) -> v8::Local<v8::Value>;

  friend class ValueRegistry;

 private:
  auto GetHandle() -> ValueHandle*;
  void SaveGlobalHandle(v8::Isolate* isolate, v8::Local<v8::Value> value);
  void CreateBackingStoreRef(v8::Isolate* isolate, v8::Local<v8::Value> value);

  IsolateObjectCollector* isolate_object_collector_;
  ValueHandle handle_;
  std::variant<std::monostate, std::vector<char>, v8::Global<v8::Value>> data_;
};

class ValueFactory {
 public:
  explicit ValueFactory(v8::Isolate* isolate,
                        IsolateObjectCollector* isolate_object_collector);

  template <typename... Params>
  auto New(Params&&... params) -> Value::Ptr;

 private:
  v8::Isolate* isolate_;
  IsolateObjectCollector* isolate_object_collector_;
};

/** We return handles to Values to the MiniRacer user side (i.e.,
 * Python), as raw pointers. To ensure we keep those handles alive while Python
 * is using them, we register them in a map, contained within this class.
 */
class ValueRegistry {
 public:
  /** Record the value in an internal map, so we don't destroy it when
   * returning a value handle to the MiniRacer user (i.e., the
   * Python side).
   */
  auto Remember(Value::Ptr ptr) -> ValueHandle*;

  /** Unrecord a value so it can be garbage collected (once any other
   * shared_ptr references are dropped).
   */
  void Forget(ValueHandle* handle);

  /** "Re-hydrate" a value from just its handle (only works if it was
   * "Remembered") */
  auto FromHandle(ValueHandle* handle) -> Value::Ptr;

  /** Count the total number of remembered values, for test purposes. */
  auto Count() -> size_t;

 private:
  std::mutex mutex_;
  std::unordered_map<ValueHandle*, std::shared_ptr<Value>> values_;
};

template <typename... Params>
inline auto ValueFactory::New(Params&&... params) -> Value::Ptr {
  return std::make_shared<Value>(isolate_, isolate_object_collector_,
                                 std::forward<Params>(params)...);
}

}  // namespace MiniRacer

#endif  // INCLUDE_MINI_RACER_VALUE_H
