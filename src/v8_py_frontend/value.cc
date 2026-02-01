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
#include <sstream>
#include <string_view>
#include <utility>
#include "isolate_manager.h"

namespace MiniRacer {

// NOLINTBEGIN(cppcoreguidelines-pro-type-union-access)

namespace {
auto InferTypeFromValue(v8::Local<v8::Value> value) -> ValueTypes {
  if (value->IsNull()) {
    return type_null;
  }
  if (value->IsUndefined()) {
    return type_undefined;
  }
  if (value->IsFunction()) {
    return type_function;
  }
  if (value->IsSymbol()) {
    return type_symbol;
  }
  if (value->IsPromise()) {
    return type_promise;
  }
  if (value->IsArray()) {
    return type_array;
  }
  if (value->IsInt32() || value->IsBigInt()) {
    return type_integer;
  }
  if (value->IsNumber()) {
    return type_double;
  }
  if (value->IsBoolean()) {
    return type_bool;
  }
  if (value->IsDate()) {
    return type_date;
  }
  if (value->IsString()) {
    return type_string;
  }
  if (value->IsArrayBufferView()) {
    return type_array_buffer_view;
  }
  if (value->IsSharedArrayBuffer()) {
    return type_shared_array_buffer;
  }
  if (value->IsArrayBuffer()) {
    return type_array_buffer;
  }
  if (value->IsObject()) {
    return type_object;
  }

  return type_invalid;
}
}  // namespace

Value::Value(v8::Isolate* isolate,
             v8::Local<v8::Context> context,
             v8::Local<v8::Value> value,
             ValueTypes type)
    : global_(isolate, value) {
  handle_.type = type;

  // For various types we store a "preview" so that the user can read data
  // without another trip through the FFI:
  if (value->IsInt32()) {
    handle_.int_val = value->Int32Value(context).ToChecked();
  } else if (value->IsBigInt()) {
    handle_.int_val = value.As<v8::BigInt>()->Int64Value();
  } else if (value->IsNumber()) {
    handle_.double_val = value->NumberValue(context).ToChecked();
  } else if (value->IsBoolean()) {
    handle_.int_val = (value->IsTrue() ? 1 : 0);
  } else if (value->IsDate()) {
    handle_.double_val = v8::Local<v8::Date>::Cast(value)->ValueOf();
  } else if (value->IsString()) {
    const v8::Local<v8::String> rstr =
        value->ToString(context).ToLocalChecked();

    handle_.len = static_cast<size_t>(rstr->Utf8LengthV2(isolate));  // in bytes
    const size_t capacity = handle_.len + 1;
    buf_.resize(capacity);
    rstr->WriteUtf8V2(isolate, buf_.data(), capacity);
    handle_.bytes = buf_.data();
  } else if (value->IsArrayBufferView()) {
    // For ArrayBuffer and friends, we store a reference to the V8 object
    // in this Value instance, and return a pointer *into* the buffer to the
    // Python side.
    const v8::Local<v8::ArrayBufferView> view =
        v8::Local<v8::ArrayBufferView>::Cast(value);

    // NOLINTBEGIN(cppcoreguidelines-pro-bounds-pointer-arithmetic)
    handle_.bytes =
        static_cast<char*>(view->Buffer()->GetBackingStore()->Data()) +
        view->ByteOffset();
    // NOLINTEND(cppcoreguidelines-pro-bounds-pointer-arithmetic)
    handle_.len = view->ByteLength();
  } else if (value->IsSharedArrayBuffer()) {
    auto backing_store =
        v8::Local<v8::SharedArrayBuffer>::Cast(value)->GetBackingStore();
    handle_.bytes = static_cast<char*>(backing_store->Data());
    handle_.len = backing_store->ByteLength();
  } else if (value->IsArrayBuffer()) {
    auto backing_store =
        v8::Local<v8::ArrayBuffer>::Cast(value)->GetBackingStore();
    handle_.bytes = static_cast<char*>(backing_store->Data());
    handle_.len = backing_store->ByteLength();
  }
}

auto Value::Global() -> v8::Global<v8::Value>* {
  return &global_;
}

auto Value::GetHandle() -> ValueHandle* {
  return &handle_;
}

// NOLINTEND(cppcoreguidelines-pro-type-union-access)

ValueFactory::ValueFactory(IsolateManager* isolate_manager)
    : isolate_manager_(isolate_manager) {}

auto ValueFactory::New(v8::Local<v8::Value> value, ValueTypes type)
    -> Value::Ptr {
  const v8::Local<v8::Context> context = isolate_manager_->GetLocalContext();
  return std::make_unique<Value>(isolate_manager_->GetIsolate(), context, value,
                                 type);
}

auto ValueFactory::NewFromAny(v8::Local<v8::Value> value) -> Value::Ptr {
  return New(value, InferTypeFromValue(value));
}

auto ValueFactory::NewFromBool(bool value) -> Value::Ptr {
  return New(v8::Boolean::New(isolate_manager_->GetIsolate(), value),
             type_bool);
}

auto ValueFactory::NewFromInt(int64_t value, ValueTypes type) -> Value::Ptr {
  v8::Isolate* isolate = isolate_manager_->GetIsolate();
  if (type == type_undefined) {
    return New(v8::Undefined(isolate), type);
  }
  if (type == type_null) {
    return New(v8::Null(isolate), type);
  }
  return New(v8::BigInt::New(isolate, value), type);
}

auto ValueFactory::NewFromDouble(double value, ValueTypes type) -> Value::Ptr {
  if (type == type_date) {
    return New(v8::Date::New(isolate_manager_->GetLocalContext(), value)
                   .ToLocalChecked(),
               type);
  }
  return New(v8::Number::New(isolate_manager_->GetIsolate(), value), type);
}

auto ValueFactory::NewFromString(std::string_view message, ValueTypes type)
    -> Value::Ptr {
  return New(v8::String::NewFromUtf8(isolate_manager_->GetIsolate(),
                                     message.data(), v8::NewStringType::kNormal,
                                     static_cast<int>(message.size()))
                 .ToLocalChecked(),
             type);
}

auto ValueFactory::NewFromException(v8::Local<v8::Message> message,
                                    v8::Local<v8::Value> exception_obj,
                                    ValueTypes type) -> Value::Ptr {
  // From v8/src/d8.cc:
  std::stringstream msg;

  // Converts a V8 value to a C string.
  auto ToCString = [](const v8::String::Utf8Value& value) {
    return (*value == nullptr) ? "<string conversion failed>" : *value;
  };

  const v8::Local<v8::Context> context = isolate_manager_->GetLocalContext();

  const v8::String::Utf8Value exception(isolate_manager_->GetIsolate(),
                                        exception_obj);
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
        isolate_manager_->GetIsolate(),
        message->GetScriptOrigin().ResourceName());
    const char* filename_string = ToCString(filename);
    const int linenum = message->GetLineNumber(context).FromMaybe(-1);
    msg << filename_string << ":" << linenum << ": " << exception_string
        << "\n";
    v8::Local<v8::String> sourceline;
    if (message->GetSourceLine(context).ToLocal(&sourceline)) {
      // Print line of source code.
      const v8::String::Utf8Value sourcelinevalue(
          isolate_manager_->GetIsolate(), sourceline);
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
        isolate_manager_->GetIsolate(), stack_trace_string.As<v8::String>());
    msg << "\n";
    msg << ToCString(stack_trace);
    msg << "\n";
  }
  return NewFromString(msg.str(), type);
}

auto ValueRegistry::Remember(Value::Ptr ptr) -> ValueHandle* {
  ValueHandle* handle = ptr->GetHandle();
  values_[handle] = std::move(ptr);
  return handle;
}

void ValueRegistry::Forget(ValueHandle* handle) {
  values_.erase(handle);
}

auto ValueRegistry::FromHandle(ValueHandle* handle) -> Value* {
  // Track all created values to relieve Python of the duty of garbage
  // collecting them in the correct order relative to the MiniRacer::Context:
  auto iter = values_.find(handle);
  if (iter == values_.end()) {
    return nullptr;
  }
  return iter->second.get();
}

auto ValueRegistry::Count() -> size_t {
  return values_.size();
}

}  // namespace MiniRacer
