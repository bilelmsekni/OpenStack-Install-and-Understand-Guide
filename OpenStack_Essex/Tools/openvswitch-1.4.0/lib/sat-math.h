/*
 * Copyright (c) 2008 Nicira Networks.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at:
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#ifndef SAT_MATH_H
#define SAT_MATH_H 1

#include <assert.h>
#include <limits.h>

/* Saturating addition: overflow yields UINT_MAX. */
static inline unsigned int
sat_add(unsigned int x, unsigned int y)
{
    return x + y >= x ? x + y : UINT_MAX;
}

/* Saturating subtraction: underflow yields 0. */
static inline unsigned int
sat_sub(unsigned int x, unsigned int y)
{
    return x >= y ? x - y : 0;
}

/* Saturating multiplication: overflow yields UINT_MAX. */
static inline unsigned int
sat_mul(unsigned int x, unsigned int y)
{
    return (!y ? 0
            : x <= UINT_MAX / y ? x * y
            : UINT_MAX);
}

#endif /* sat-math.h */
