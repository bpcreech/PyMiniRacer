#ifndef INCLUDE_MINI_RACER_HEAP_REPORTER_H
#define INCLUDE_MINI_RACER_HEAP_REPORTER_H

#include <v8-isolate.h>
#include "value.h"

namespace MiniRacer {

/** Report fun facts about an isolate heap */
class HeapReporter {
 public:
  explicit HeapReporter(ValueFactory* val_factory);

  auto HeapSnapshot(v8::Isolate* isolate) -> Value::Ptr;
  auto HeapStats(v8::Isolate* isolate) -> Value::Ptr;

 private:
  ValueFactory* val_factory_;
};

}  // end namespace MiniRacer

#endif  // INCLUDE_MINI_RACER_HEAP_REPORTER_H
