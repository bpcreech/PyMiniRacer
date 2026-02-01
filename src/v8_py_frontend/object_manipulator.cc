#include "object_manipulator.h"
#include <v8-container.h>
#include <v8-context.h>
#include <v8-exception.h>
#include <v8-function.h>
#include <v8-local-handle.h>
#include <v8-object.h>
#include <v8-primitive.h>
#include <cstdint>
#include <vector>
#include "isolate_manager.h"
#include "value.h"

namespace MiniRacer {
ObjectManipulator::ObjectManipulator(IsolateManager* isolate_manager,
                                     ValueFactory* val_factory)
    : isolate_manager_(isolate_manager), val_factory_(val_factory) {}

auto ObjectManipulator::GetIdentityHash(Value* obj_ptr) -> Value::Ptr {
  v8::Isolate* isolate = isolate_manager_->GetIsolate();

  const v8::Local<v8::Value> local_obj_val = obj_ptr->Global()->Get(isolate);
  const v8::Local<v8::Object> local_obj = local_obj_val.As<v8::Object>();

  return val_factory_->NewFromInt(local_obj->GetIdentityHash(), type_integer);
}

auto ObjectManipulator::GetOwnPropertyNames(Value* obj_ptr) const
    -> Value::Ptr {
  v8::Isolate* isolate = isolate_manager_->GetIsolate();

  const v8::Local<v8::Value> local_obj_val = obj_ptr->Global()->Get(isolate);
  const v8::Local<v8::Object> local_obj = local_obj_val.As<v8::Object>();

  const v8::Local<v8::Context> context = isolate_manager_->GetLocalContext();

  const v8::Local<v8::Array> names =
      local_obj->GetPropertyNames(context).ToLocalChecked();

  return val_factory_->NewFromAny(names);
}

auto ObjectManipulator::Get(Value* obj_ptr, Value* key_ptr) -> Value::Ptr {
  v8::Isolate* isolate = isolate_manager_->GetIsolate();

  const v8::Local<v8::Value> local_obj_val = obj_ptr->Global()->Get(isolate);
  const v8::Local<v8::Object> local_obj = local_obj_val.As<v8::Object>();
  const v8::Local<v8::Value> local_key = key_ptr->Global()->Get(isolate);

  const v8::Local<v8::Context> context = isolate_manager_->GetLocalContext();

  if (!local_obj->Has(context, local_key).ToChecked()) {
    return val_factory_->NewFromString("No such key", type_key_exception);
  }

  const v8::Local<v8::Value> value =
      local_obj->Get(context, local_key).ToLocalChecked();

  return val_factory_->NewFromAny(value);
}

auto ObjectManipulator::Set(Value* obj_ptr, Value* key_ptr, Value* val_ptr)
    -> Value::Ptr {
  v8::Isolate* isolate = isolate_manager_->GetIsolate();

  const v8::Local<v8::Value> local_obj_val = obj_ptr->Global()->Get(isolate);
  const v8::Local<v8::Object> local_obj = local_obj_val.As<v8::Object>();
  const v8::Local<v8::Value> local_key = key_ptr->Global()->Get(isolate);
  const v8::Local<v8::Value> local_value = val_ptr->Global()->Get(isolate);

  const v8::Local<v8::Context> context = isolate_manager_->GetLocalContext();

  local_obj->Set(context, local_key, local_value).ToChecked();

  return val_factory_->NewFromBool(true);
}

auto ObjectManipulator::Del(Value* obj_ptr, Value* key_ptr) -> Value::Ptr {
  v8::Isolate* isolate = isolate_manager_->GetIsolate();

  const v8::Local<v8::Value> local_obj_val = obj_ptr->Global()->Get(isolate);
  const v8::Local<v8::Object> local_obj = local_obj_val.As<v8::Object>();
  const v8::Local<v8::Value> local_key = key_ptr->Global()->Get(isolate);

  const v8::Local<v8::Context> context = isolate_manager_->GetLocalContext();

  if (!local_obj->Has(context, local_key).ToChecked()) {
    return val_factory_->NewFromString("No such key", type_key_exception);
  }

  return val_factory_->NewFromBool(
      local_obj->Delete(context, local_key).ToChecked());
}

auto ObjectManipulator::Splice(Value* obj_ptr,
                               int32_t start,
                               int32_t delete_count,
                               Value* new_val_ptr) -> Value::Ptr {
  v8::Isolate* isolate = isolate_manager_->GetIsolate();

  const v8::Local<v8::Value> local_obj_val = obj_ptr->Global()->Get(isolate);
  const v8::Local<v8::Object> local_obj = local_obj_val.As<v8::Object>();

  // Array.prototype.splice doesn't exist in C++ in V8. We have to find the JS
  // function and call it:
  const v8::Local<v8::String> splice_name =
      v8::String::NewFromUtf8Literal(isolate, "splice");

  const v8::Local<v8::Context> context = isolate_manager_->GetLocalContext();

  v8::Local<v8::Value> splice_val;
  if (!local_obj->Get(context, splice_name).ToLocal(&splice_val)) {
    return val_factory_->NewFromString("no splice method on object",
                                       type_execute_exception);
  }

  if (!splice_val->IsFunction()) {
    return val_factory_->NewFromString("splice member is not a function",
                                       type_execute_exception);
  }

  const v8::Local<v8::Function> splice_func = splice_val.As<v8::Function>();

  const v8::TryCatch trycatch(isolate);

  std::vector<v8::Local<v8::Value>> argv = {
      v8::Int32::New(isolate, start),
      v8::Int32::New(isolate, delete_count),
  };
  if (new_val_ptr != nullptr) {
    argv.push_back(new_val_ptr->Global()->Get(isolate));
  }

  v8::MaybeLocal<v8::Value> maybe_value = splice_func->Call(
      context, local_obj, static_cast<int>(argv.size()), argv.data());
  if (maybe_value.IsEmpty()) {
    return val_factory_->NewFromException(
        trycatch.Message(), trycatch.Exception(), type_execute_exception);
  }

  return val_factory_->NewFromAny(maybe_value.ToLocalChecked());
}

auto ObjectManipulator::Push(Value* obj_ptr, Value* new_val_ptr) -> Value::Ptr {
  v8::Isolate* isolate = isolate_manager_->GetIsolate();

  const v8::Local<v8::Value> local_obj_val = obj_ptr->Global()->Get(isolate);
  const v8::Local<v8::Object> local_obj = local_obj_val.As<v8::Object>();

  // Array.prototype.push doesn't exist in C++ in V8. We have to find the JS
  // function and call it:
  const v8::Local<v8::String> push_name =
      v8::String::NewFromUtf8Literal(isolate, "push");

  const v8::Local<v8::Context> context = isolate_manager_->GetLocalContext();

  v8::Local<v8::Value> push_val;
  if (!local_obj->Get(context, push_name).ToLocal(&push_val)) {
    return val_factory_->NewFromString("no push method on object",
                                       type_execute_exception);
  }

  if (!push_val->IsFunction()) {
    return val_factory_->NewFromString("push member is not a function",
                                       type_execute_exception);
  }

  const v8::Local<v8::Function> push_func = push_val.As<v8::Function>();

  const v8::TryCatch trycatch(isolate);

  std::vector<v8::Local<v8::Value>> argv = {
      new_val_ptr->Global()->Get(isolate)};

  v8::MaybeLocal<v8::Value> maybe_value = push_func->Call(
      context, local_obj, static_cast<int>(argv.size()), argv.data());
  if (maybe_value.IsEmpty()) {
    return val_factory_->NewFromException(
        trycatch.Message(), trycatch.Exception(), type_execute_exception);
  }

  return val_factory_->NewFromAny(maybe_value.ToLocalChecked());
}

auto ObjectManipulator::Call(Value* func_ptr, Value* this_ptr, Value* argv_ptr)
    -> Value::Ptr {
  v8::Isolate* isolate = isolate_manager_->GetIsolate();

  const v8::Local<v8::Value> local_func_val = func_ptr->Global()->Get(isolate);

  if (!local_func_val->IsFunction()) {
    return val_factory_->NewFromString("function is not callable",
                                       type_execute_exception);
  }

  const v8::Local<v8::Function> local_func = local_func_val.As<v8::Function>();

  v8::Local<v8::Value> local_this;
  if (this_ptr == nullptr) {
    local_this = v8::Undefined(isolate);
  } else {
    local_this = this_ptr->Global()->Get(isolate);
  }

  const v8::Local<v8::Value> local_argv_value =
      argv_ptr->Global()->Get(isolate);

  if (!local_argv_value->IsArray()) {
    return val_factory_->NewFromString("argv is not an array",
                                       type_execute_exception);
  }

  const v8::Local<v8::Array> local_argv_array =
      local_argv_value.As<v8::Array>();

  const v8::Local<v8::Context> context = isolate_manager_->GetLocalContext();

  std::vector<v8::Local<v8::Value>> argv;
  for (uint32_t i = 0; i < local_argv_array->Length(); i++) {
    argv.push_back(local_argv_array->Get(context, i).ToLocalChecked());
  }

  const v8::TryCatch trycatch(isolate);

  v8::MaybeLocal<v8::Value> maybe_value = local_func->Call(
      context, local_this, static_cast<int>(argv.size()), argv.data());
  if (maybe_value.IsEmpty()) {
    return val_factory_->NewFromException(
        trycatch.Message(), trycatch.Exception(), type_execute_exception);
  }

  return val_factory_->NewFromAny(maybe_value.ToLocalChecked());
}

}  // end namespace MiniRacer
