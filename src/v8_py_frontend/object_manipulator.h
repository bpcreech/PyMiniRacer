#ifndef INCLUDE_MINI_RACER_OBJECT_MANIPULATOR_H
#define INCLUDE_MINI_RACER_OBJECT_MANIPULATOR_H

#include <v8-isolate.h>
#include <v8-persistent-handle.h>
#include <cstdint>
#include "context_holder.h"
#include "value.h"

namespace MiniRacer {

/** Manipulates v8::Object attributes, exposing APIs reachable from C (through
 * the MiniRacer::Context).
 *
 * All methods in this function assume that the caller holds the Isolate lock
 * (i.e., is operating from the isolate message pump), and memory management of
 * the Value pointers is done by the caller. */
class ObjectManipulator {
 public:
  ObjectManipulator(ContextHolder* context, ValueFactory* val_factory);

  auto GetIdentityHash(v8::Isolate* isolate, Value* obj_ptr) -> Value::Ptr;
  auto GetOwnPropertyNames(v8::Isolate* isolate,
                           Value* obj_ptr) const -> Value::Ptr;
  auto Get(v8::Isolate* isolate, Value* obj_ptr, Value* key_ptr) -> Value::Ptr;
  auto Set(v8::Isolate* isolate,
           Value* obj_ptr,
           Value* key_ptr,
           Value* val_ptr) -> Value::Ptr;
  auto Del(v8::Isolate* isolate, Value* obj_ptr, Value* key_ptr) -> Value::Ptr;
  auto Splice(v8::Isolate* isolate,
              Value* obj_ptr,
              int32_t start,
              int32_t delete_count,
              Value* new_val_ptr) -> Value::Ptr;
  auto Push(v8::Isolate* isolate,
            Value* obj_ptr,
            Value* new_val_ptr) -> Value::Ptr;
  auto Call(v8::Isolate* isolate,
            Value* func_ptr,
            Value* this_ptr,
            Value* argv_ptr) -> Value::Ptr;

 private:
  ContextHolder* context_;
  ValueFactory* val_factory_;
};

}  // end namespace MiniRacer

#endif  // INCLUDE_MINI_RACER_OBJECT_MANIPULATOR_H
