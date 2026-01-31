#ifndef INCLUDE_MINI_RACER_CODE_EVALUATOR_H
#define INCLUDE_MINI_RACER_CODE_EVALUATOR_H

#include <v8-exception.h>
#include <v8-isolate.h>
#include <v8-local-handle.h>
#include <v8-persistent-handle.h>
#include "context_holder.h"
#include "isolate_memory_monitor.h"
#include "value.h"

namespace MiniRacer {

/** Parse and run arbitrary scripts within an isolate. */
class CodeEvaluator {
 public:
  CodeEvaluator(ContextHolder* context,
                ValueFactory* val_factory,
                IsolateMemoryMonitor* memory_monitor);

  auto Eval(v8::Isolate* isolate, Value* code_ptr) -> Value::Ptr;

 private:
  ContextHolder* context_;
  ValueFactory* val_factory_;
  IsolateMemoryMonitor* memory_monitor_;
};

}  // end namespace MiniRacer

#endif  // INCLUDE_MINI_RACER_CODE_EVALUATOR_H
