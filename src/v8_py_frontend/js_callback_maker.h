#ifndef INCLUDE_MINI_RACER_JS_CALLBACK_MAKER_H
#define INCLUDE_MINI_RACER_JS_CALLBACK_MAKER_H

#include <v8-container.h>
#include <v8-context.h>
#include <v8-function-callback.h>
#include <v8-persistent-handle.h>
#include <cstdint>
#include <memory>
#include <mutex>
#include "callback.h"
#include "id_maker.h"
#include "isolate_manager.h"
#include "value.h"

namespace MiniRacer {

/** A callback caller contains the bundle of items needed to successfully
 * handle a callback from JS by calling through to the MiniRacer user (i.e.,
 * Python). A JSCallbackCaller is affine to a single MiniRacer::Context (and so
 * multiple callbacks can share a single JSCallbackCaller).
 */
class JSCallbackCaller {
 public:
  JSCallbackCaller(ValueFactory* val_factory,
                   ValueRegistry* val_registry,
                   RawCallback callback);

  void DoCallback(uint64_t callback_id, v8::Local<v8::Array> args);

 private:
  ValueFactory* val_factory_;
  ValueRegistry* val_registry_;
  RawCallback callback_;
};

/** Creates a JS callback wrapped around the given C callback function pointer.
 */
class JSCallbackMaker {
 public:
  JSCallbackMaker(IsolateManager* isolate_manager,
                  ValueFactory* val_factory,
                  ValueRegistry* val_registry,
                  RawCallback callback);

  auto MakeJSCallback(uint64_t callback_id) -> Value::Ptr;

 private:
  static void OnCalledStatic(const v8::FunctionCallbackInfo<v8::Value>& info);
  static auto GetCallbackCallers()
      -> std::shared_ptr<IdMaker<JSCallbackCaller>>;

  static std::shared_ptr<IdMaker<JSCallbackCaller>> callback_callers_;
  static std::once_flag callback_callers_init_flag_;

  IsolateManager* isolate_manager_;
  ValueFactory* val_factory_;
  IdHolder<JSCallbackCaller> callback_caller_holder_;
};

}  // namespace MiniRacer

#endif  // INCLUDE_MINI_RACER_JS_CALLBACK_MAKER_H
