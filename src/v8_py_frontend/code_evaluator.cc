#include "code_evaluator.h"

#include <v8-context.h>
#include <v8-exception.h>
#include <v8-isolate.h>
#include <v8-local-handle.h>
#include <v8-message.h>
#include <v8-persistent-handle.h>
#include <v8-primitive.h>
#include <v8-script.h>
#include <v8-value.h>
#include "isolate_manager.h"
#include "isolate_memory_monitor.h"
#include "value.h"

namespace MiniRacer {

CodeEvaluator::CodeEvaluator(IsolateManager* isolate_manager,
                             ValueFactory* val_factory,
                             IsolateMemoryMonitor* memory_monitor)
    : isolate_manager_(isolate_manager),
      val_factory_(val_factory),
      memory_monitor_(memory_monitor) {}

auto CodeEvaluator::Eval(Value* code_ptr) -> Value::Ptr {
  v8::Isolate* isolate = isolate_manager_->GetIsolate();

  const v8::TryCatch trycatch(isolate);

  const v8::Local<v8::Value> local_code_val = code_ptr->Global()->Get(isolate);

  if (!local_code_val->IsString()) {
    return val_factory_->NewFromString("code is not a string",
                                       type_execute_exception);
  }

  const v8::Local<v8::String> local_code_str = local_code_val.As<v8::String>();

  // Provide a name just for exception messages:
  v8::ScriptOrigin script_origin(
      v8::String::NewFromUtf8Literal(isolate, "<anonymous>"));

  const v8::Local<v8::Context> context = isolate_manager_->GetLocalContext();

  v8::Local<v8::Script> script;
  if (!v8::Script::Compile(context, local_code_str, &script_origin)
           .ToLocal(&script) ||
      script.IsEmpty()) {
    return val_factory_->NewFromException(
        trycatch.Message(), trycatch.Exception(), type_parse_exception);
  }

  v8::MaybeLocal<v8::Value> maybe_value = script->Run(context);
  if (!maybe_value.IsEmpty()) {
    return val_factory_->NewFromAny(maybe_value.ToLocalChecked());
  }

  // Didn't execute. Find an error:
  if (memory_monitor_->IsHardMemoryLimitReached()) {
    return val_factory_->NewFromString("", type_oom_exception);
  }

  ValueTypes result_type = type_execute_exception;
  if (trycatch.HasTerminated()) {
    result_type = type_terminated_exception;
  }

  return val_factory_->NewFromException(trycatch.Message(),
                                        trycatch.Exception(), result_type);
}

}  // end namespace MiniRacer
