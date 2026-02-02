#include "js_callback_maker.h"
#include <v8-container.h>
#include <v8-context.h>
#include <v8-function-callback.h>
#include <v8-function.h>
#include <v8-local-handle.h>
#include <v8-persistent-handle.h>
#include <v8-primitive.h>
#include <array>
#include <cstdint>
#include <memory>
#include <mutex>
#include "callback.h"
#include "id_maker.h"
#include "isolate_manager.h"
#include "value.h"

namespace MiniRacer {

JSCallbackCaller::JSCallbackCaller(ValueFactory* val_factory,
                                   ValueRegistry* val_registry,
                                   RawCallback callback)
    : val_factory_(val_factory),
      val_registry_(val_registry),
      callback_(callback) {}

void JSCallbackCaller::DoCallback(uint64_t callback_id,
                                  v8::Local<v8::Array> args) {
  callback_(callback_id,
            val_registry_->Remember(val_factory_->NewFromAny(args)));
}

std::shared_ptr<IdMaker<JSCallbackCaller>> JSCallbackMaker::callback_callers_;
std::once_flag JSCallbackMaker::callback_callers_init_flag_;

auto JSCallbackMaker::GetCallbackCallers()
    -> std::shared_ptr<IdMaker<JSCallbackCaller>> {
  std::call_once(callback_callers_init_flag_, []() {
    callback_callers_ = std::make_shared<IdMaker<JSCallbackCaller>>();
  });
  return callback_callers_;
}

JSCallbackMaker::JSCallbackMaker(IsolateManager* isolate_manager,
                                 ValueFactory* val_factory,
                                 ValueRegistry* val_registry,
                                 RawCallback callback)
    : isolate_manager_(isolate_manager),
      val_factory_(val_factory),
      callback_caller_holder_(std::make_shared<JSCallbackCaller>(val_factory,
                                                                 val_registry,
                                                                 callback),
                              GetCallbackCallers()) {}

auto JSCallbackMaker::MakeJSCallback(uint64_t callback_id) -> Value::Ptr {
  v8::Isolate* isolate = isolate_manager_->GetIsolate();

  // We create a JS Array containing:
  // {a BigInt indicating the callback caller ID, a BigInt indicating the
  // callback ID}
  // ... And stuff it into the callback, so we can understand the context when
  // we're called back.
  // We do this instead of embedding pointers to C++ objects in the objects
  // (using v8::External) so that we can control object teardown. In this model,
  // we tear down the C++ JSCallbackMaker and its dependencies when the
  // MiniRacer::Context is torn down, and if a callback executes after the
  // underlying callback caller is torn down, that callback is safely ignored.
  const v8::Local<v8::BigInt> callback_caller_id_bigint =
      v8::BigInt::NewFromUnsigned(isolate, callback_caller_holder_.GetId());
  const v8::Local<v8::BigInt> callback_id_bigint =
      v8::BigInt::NewFromUnsigned(isolate, callback_id);
  std::array<v8::Local<v8::Value>, 2> data_elements = {
      callback_caller_id_bigint, callback_id_bigint};

  const v8::Local<v8::Array> data =
      v8::Array::New(isolate, data_elements.data(), data_elements.size());

  const v8::Local<v8::Context> context = isolate_manager_->GetLocalContext();

  v8::Local<v8::Function> func;
  if (!v8::Function::New(context, &JSCallbackMaker::OnCalledStatic, data)
           .ToLocal(&func)) {
    return val_factory_->NewFromString("Could not create func",
                                       type_execute_exception);
  }

  return val_factory_->NewFromAny(func);
}

void JSCallbackMaker::OnCalledStatic(
    const v8::FunctionCallbackInfo<v8::Value>& info) {
  v8::Isolate* isolate = info.GetIsolate();
  const v8::HandleScope scope(isolate);
  const v8::Local<v8::Context> context = isolate->GetCurrentContext();

  const v8::Local<v8::Value> data_value = info.Data();

  if (!data_value->IsArray()) {
    return;
  }
  const v8::Local<v8::Array> data_array = data_value.As<v8::Array>();

  if (data_array->Length() != 2) {
    return;
  }
  const v8::MaybeLocal<v8::Value> callback_caller_id_value_maybe =
      data_array->Get(context, 0);
  const v8::MaybeLocal<v8::Value> callback_id_value_maybe =
      data_array->Get(context, 1);

  v8::Local<v8::Value> callback_caller_id_value;
  if (!callback_caller_id_value_maybe.ToLocal(&callback_caller_id_value)) {
    return;
  }

  if (!callback_caller_id_value->IsBigInt()) {
    return;
  }
  const v8::Local<v8::BigInt> callback_caller_id_bigint =
      callback_caller_id_value.As<v8::BigInt>();

  bool lossless = false;
  const uint64_t callback_caller_id =
      callback_caller_id_bigint->Uint64Value(&lossless);
  if (!lossless) {
    return;
  }

  v8::Local<v8::Value> callback_id_value;
  if (!callback_id_value_maybe.ToLocal(&callback_id_value)) {
    return;
  }

  if (!callback_id_value->IsBigInt()) {
    return;
  }
  const v8::Local<v8::BigInt> callback_id_bigint =
      callback_id_value.As<v8::BigInt>();

  const uint64_t callback_id = callback_id_bigint->Uint64Value(&lossless);
  if (!lossless) {
    return;
  }

  int idx = 0;
  const v8::Local<v8::Array> args =
      v8::Array::New(context, info.Length(), [&idx, &info] {
        return info[idx++];
      }).ToLocalChecked();

  const std::shared_ptr<JSCallbackCaller> callback_caller =
      callback_callers_->GetObject(callback_caller_id);
  if (!callback_caller) {
    return;
  }

  callback_caller->DoCallback(callback_id, args);
}

}  // end namespace MiniRacer
