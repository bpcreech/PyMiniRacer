#include "value.h"

#include <v8-array-buffer.h>
#include <v8-date.h>
#include <v8-exception.h>
#include <v8-local-handle.h>
#include <v8-persistent-handle.h>
#include <v8-primitive.h>
#include <v8-value.h>
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <ios>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>
#include "isolate_object_collector.h"

namespace MiniRacer {

// NOLINTBEGIN(cppcoreguidelines-pro-type-union-access)

Value::Value(v8::Isolate* isolate,
             IsolateObjectCollector* isolate_object_collector,
             v8::Local<v8::Context> context,
             v8::Local<v8::Value> value)
    : isolate_object_collector_(isolate_object_collector) {
  if (value->IsNull()) {
    handle_.type = type_null;
  } else if (value->IsUndefined()) {
    handle_.type = type_undefined;
  } else if (value->IsInt32()) {
    handle_.type = type_integer;
    auto val = value->Int32Value(context).ToChecked();
    handle_.int_val = val;
  }
  // ECMA-262, 4.3.20
  // http://www.ecma-international.org/ecma-262/5.1/#sec-4.3.19
  else if (value->IsNumber()) {
    handle_.type = type_double;
    const double val = value->NumberValue(context).ToChecked();
    handle_.double_val = val;
  } else if (value->IsBoolean()) {
    handle_.type = type_bool;
    handle_.int_val = (value->IsTrue() ? 1 : 0);
  } else if (value->IsFunction()) {
    handle_.type = type_function;
    SaveGlobalHandle(isolate, value);
  } else if (value->IsSymbol()) {
    handle_.type = type_symbol;
    SaveGlobalHandle(isolate, value);
  } else if (value->IsDate()) {
    handle_.type = type_date;
    const v8::Local<v8::Date> date = v8::Local<v8::Date>::Cast(value);

    const double timestamp = date->ValueOf();
    handle_.double_val = timestamp;
  } else if (value->IsString()) {
    const v8::Local<v8::String> rstr =
        value->ToString(context).ToLocalChecked();

    handle_.type = type_str_utf8;
    handle_.len = static_cast<size_t>(rstr->Utf8LengthV2(isolate));  // in bytes
    const size_t capacity = handle_.len + 1;
    auto& msg = data_.emplace<std::vector<char>>();
    msg.resize(capacity);
    rstr->WriteUtf8V2(isolate, msg.data(), capacity);
    handle_.bytes = msg.data();
  } else if (value->IsSharedArrayBuffer() || value->IsArrayBuffer() ||
             value->IsArrayBufferView()) {
    CreateBackingStoreRef(isolate, value);
  } else if (value->IsPromise()) {
    handle_.type = type_promise;
    SaveGlobalHandle(isolate, value);
  } else if (value->IsArray()) {
    handle_.type = type_array;
    SaveGlobalHandle(isolate, value);
  } else if (value->IsObject()) {
    handle_.type = type_object;
    SaveGlobalHandle(isolate, value);
  }
}

Value::Value(v8::Isolate* isolate,
             IsolateObjectCollector* isolate_object_collector,
             std::string_view val,
             ValueTypes type)
    : isolate_object_collector_(isolate_object_collector) {
  handle_.len = val.size();
  handle_.type = type;
  auto& msg = data_.emplace<std::vector<char>>();
  msg.resize(handle_.len + 1);
  std::copy(val.begin(), val.end(), msg.data());
  msg[handle_.len] = '\0';
  handle_.bytes = msg.data();
}

Value::Value(v8::Isolate* isolate,
             IsolateObjectCollector* isolate_object_collector,
             bool val)
    : isolate_object_collector_(isolate_object_collector) {
  handle_.len = 0;
  handle_.type = type_bool;
  handle_.int_val = val ? 1 : 0;
}

Value::Value(v8::Isolate* isolate,
             IsolateObjectCollector* isolate_object_collector,
             int64_t val,
             ValueTypes type)
    : isolate_object_collector_(isolate_object_collector) {
  handle_.len = 0;
  handle_.type = type;
  handle_.int_val = val;
}

Value::Value(v8::Isolate* isolate,
             IsolateObjectCollector* isolate_object_collector,
             double val,
             ValueTypes type)
    : isolate_object_collector_(isolate_object_collector) {
  handle_.len = 0;
  handle_.type = type;
  handle_.double_val = val;
}

namespace {
// From v8/src/d8.cc:
auto ExceptionToString(v8::Isolate* isolate,
                       v8::Local<v8::Context> context,
                       v8::Local<v8::Message> message,
                       v8::Local<v8::Value> exception_obj) -> std::string {
  std::stringstream msg;

  // Converts a V8 value to a C string.
  auto ToCString = [](const v8::String::Utf8Value& value) {
    return (*value == nullptr) ? "<string conversion failed>" : *value;
  };

  const v8::String::Utf8Value exception(isolate, exception_obj);
  const char* exception_string = ToCString(exception);
  if (message.IsEmpty()) {
    // V8 didn't provide any extra information about this error; just
    // print the exception.
    msg << exception_string << "\n";
  } else if (message->GetScriptOrigin().Options().IsWasm()) {
    // Print wasm-function[(function index)]:(offset): (message).
    const int function_index = message->GetWasmFunctionIndex();
    const int offset = message->GetStartColumn(context).FromJust();
    msg << "wasm-function[" << function_index << "]:0x" << std::hex << offset
        << std::dec << ": " << exception_string << "\n";
  } else {
    // Print (filename):(line number): (message).
    const v8::String::Utf8Value filename(
        isolate, message->GetScriptOrigin().ResourceName());
    const char* filename_string = ToCString(filename);
    const int linenum = message->GetLineNumber(context).FromMaybe(-1);
    msg << filename_string << ":" << linenum << ": " << exception_string
        << "\n";
    v8::Local<v8::String> sourceline;
    if (message->GetSourceLine(context).ToLocal(&sourceline)) {
      // Print line of source code.
      const v8::String::Utf8Value sourcelinevalue(isolate, sourceline);
      const char* sourceline_string = ToCString(sourcelinevalue);
      msg << sourceline_string << "\n";
      // Print wavy underline (GetUnderline is deprecated).
      const int start = message->GetStartColumn();
      const int end = std::max(message->GetEndColumn(), start + 1);
      for (int i = 0; i < start; i++) {
        msg << " ";
      }
      for (int i = start; i < end; i++) {
        msg << "^";
      }
      msg << "\n";
    }
  }
  v8::Local<v8::Value> stack_trace_string;
  if (v8::TryCatch::StackTrace(context, exception_obj)
          .ToLocal(&stack_trace_string) &&
      stack_trace_string->IsString()) {
    const v8::String::Utf8Value stack_trace(
        isolate, stack_trace_string.As<v8::String>());
    msg << "\n";
    msg << ToCString(stack_trace);
    msg << "\n";
  }
  return msg.str();
}
}  // end anonymous namespace

Value::Value(v8::Isolate* isolate,
             IsolateObjectCollector* isolate_object_collector,
             v8::Local<v8::Context> context,
             v8::Local<v8::Message> message,
             v8::Local<v8::Value> exception_obj,
             ValueTypes result_type)
    : Value(isolate,
            isolate_object_collector,
            ExceptionToString(isolate, context, message, exception_obj),
            result_type) {}

Value::~Value() {
  if (std::holds_alternative<v8::Global<v8::Value>>(data_)) {
    isolate_object_collector_->Collect(
        std::get<v8::Global<v8::Value>>(std::move(data_)));
  }
}

auto Value::ToV8Value(v8::Isolate* isolate,
                      v8::Local<v8::Context> context) -> v8::Local<v8::Value> {
  // If we've saved a handle to a v8::Global, we can return the exact v8
  // value to which this Value refers:
  auto* global_handle = std::get_if<v8::Global<v8::Value>>(&data_);
  if (global_handle != nullptr) {
    return global_handle->Get(isolate);
  }

  // Otherwise, try and rehydrate a v8::Value based on data stored in the
  // ValueHandle:

  if (handle_.type == type_null) {
    return v8::Null(isolate);
  }

  if (handle_.type == type_undefined) {
    return v8::Undefined(isolate);
  }

  if (handle_.type == type_integer) {
    return v8::Integer::New(isolate, static_cast<int32_t>(handle_.int_val));
  }

  if (handle_.type == type_double) {
    return v8::Number::New(isolate, handle_.double_val);
  }

  if (handle_.type == type_bool) {
    return v8::Boolean::New(isolate, handle_.int_val != 0);
  }

  if (handle_.type == type_date) {
    return v8::Date::New(context, handle_.double_val).ToLocalChecked();
  }

  if (handle_.type == type_str_utf8) {
    return v8::String::NewFromUtf8(isolate, handle_.bytes,
                                   v8::NewStringType::kNormal,
                                   static_cast<int>(handle_.len))
        .ToLocalChecked();
  }

  // Unknown type!
  return v8::Undefined(isolate);
}

auto Value::GetHandle() -> ValueHandle* {
  return &handle_;
}

void Value::SaveGlobalHandle(v8::Isolate* isolate, v8::Local<v8::Value> value) {
  data_.emplace<v8::Global<v8::Value>>(isolate, value);
}

void Value::CreateBackingStoreRef(v8::Isolate* isolate,
                                  v8::Local<v8::Value> value) {
  // For ArrayBuffer and friends, we store a reference to the V8 object
  // in this Value instance, and return a pointer *into* the buffer to the
  // Python side.

  size_t offset = 0;
  size_t size = 0;
  std::shared_ptr<v8::BackingStore> backing_store;

  if (value->IsArrayBufferView()) {
    const v8::Local<v8::ArrayBufferView> view =
        v8::Local<v8::ArrayBufferView>::Cast(value);

    backing_store = view->Buffer()->GetBackingStore();
    offset = view->ByteOffset();
    size = view->ByteLength();
  } else if (value->IsSharedArrayBuffer()) {
    backing_store =
        v8::Local<v8::SharedArrayBuffer>::Cast(value)->GetBackingStore();
    size = backing_store->ByteLength();
  } else {
    backing_store = v8::Local<v8::ArrayBuffer>::Cast(value)->GetBackingStore();
    size = backing_store->ByteLength();
  }

  handle_.type = value->IsSharedArrayBuffer() ? type_shared_array_buffer
                                              : type_array_buffer;
  // NOLINTBEGIN(cppcoreguidelines-pro-bounds-pointer-arithmetic)
  handle_.bytes = static_cast<char*>(backing_store->Data()) + offset;
  // NOLINTEND(cppcoreguidelines-pro-bounds-pointer-arithmetic)
  handle_.len = size;

  SaveGlobalHandle(isolate, value);
}

// NOLINTEND(cppcoreguidelines-pro-type-union-access)

ValueFactory::ValueFactory(v8::Isolate* isolate,
                           IsolateObjectCollector* isolate_object_collector)
    : isolate_(isolate), isolate_object_collector_(isolate_object_collector) {}

auto ValueRegistry::Remember(Value::Ptr ptr) -> ValueHandle* {
  const std::lock_guard<std::mutex> lock(mutex_);
  ValueHandle* handle = ptr->GetHandle();
  values_[handle] = std::move(ptr);
  return handle;
}

void ValueRegistry::Forget(ValueHandle* handle) {
  const std::lock_guard<std::mutex> lock(mutex_);
  values_.erase(handle);
}

auto ValueRegistry::FromHandle(ValueHandle* handle) -> Value::Ptr {
  // Track all created values to relieve Python of the duty of garbage
  // collecting them in the correct order relative to the MiniRacer::Context:
  const std::lock_guard<std::mutex> lock(mutex_);
  auto iter = values_.find(handle);
  if (iter == values_.end()) {
    return {};
  }
  return iter->second;
}

auto ValueRegistry::Count() -> size_t {
  const std::lock_guard<std::mutex> lock(mutex_);
  return values_.size();
}

}  // namespace MiniRacer
