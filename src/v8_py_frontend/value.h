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
#include <string_view>
#include <unordered_map>
#include <vector>
#include "isolate_manager.h"

namespace MiniRacer {

enum ValueTypes : uint8_t {
  type_invalid = 0,
  type_null = 1,
  type_bool = 2,
  type_integer = 3,
  type_double = 4,
  type_string = 5,
  type_array = 6,
  // type_hash      =   7,  // deprecated
  type_date = 8,
  type_symbol = 9,
  type_object = 10,
  type_undefined = 11,

  type_function = 100,
  type_shared_array_buffer = 101,
  type_array_buffer = 102,
  type_array_buffer_view = 103,
  type_promise = 104,

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
        v8::Local<v8::Context> context,
        v8::Local<v8::Value> value,
        ValueTypes type);

  using Ptr = std::unique_ptr<Value>;

  auto Global() -> v8::Global<v8::Value>*;

  friend class ValueRegistry;

 private:
  auto GetHandle() -> ValueHandle*;
  void SaveGlobalHandle(v8::Isolate* isolate, v8::Local<v8::Value> value);
  void CreateBackingStoreRef(v8::Isolate* isolate, v8::Local<v8::Value> value);

  ValueHandle handle_;
  v8::Global<v8::Value> global_;
  std::vector<char> buf_;
};

class ValueFactory {
 public:
  explicit ValueFactory(IsolateManager* isolate_manager);

  auto New(v8::Local<v8::Value> value, ValueTypes type) -> Value::Ptr;

  auto NewFromAny(v8::Local<v8::Value> value) -> Value::Ptr;

  auto NewFromBool(bool value) -> Value::Ptr;

  auto NewFromInt(int64_t value, ValueTypes type) -> Value::Ptr;

  auto NewFromDouble(double value, ValueTypes type) -> Value::Ptr;

  auto NewFromString(std::string_view message, ValueTypes type) -> Value::Ptr;

  auto NewFromException(v8::Local<v8::Message> message,
                        v8::Local<v8::Value> exception_obj,
                        ValueTypes type) -> Value::Ptr;

 private:
  IsolateManager* isolate_manager_;
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
  auto FromHandle(ValueHandle* handle) -> Value*;

  /** Count the total number of remembered values, for test purposes. */
  auto Count() -> size_t;

 private:
  std::unordered_map<ValueHandle*, Value::Ptr> values_;
};

}  // namespace MiniRacer

#endif  // INCLUDE_MINI_RACER_VALUE_H
