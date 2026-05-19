# 学生服务详细设计

**文档ID**: lld-student_service-001
**类型**: LLD
**模块**: 学生服务 (Student Service)
**作者**: mde_agent
**创建时间**: 2026-05-19
**版本**: 1
**关联文档**: [PRD: 学生管理系统](../prd/prd-001.json), [SAD: 学生管理系统架构方案](../sad/sad-001.json)

---

## 1. 模块概述

学生服务是学生管理系统的核心微服务之一，负责学生基本信息的增删改查操作。本服务采用分层架构（Controller → Service → Repository），通过 RESTful API 对外暴露接口，数据存储于 MySQL 独立表空间，支持 Redis 缓存热点查询，减少数据库读压力。

### 1.1 职责范围

- 学生基本信息的创建与录入（学号唯一性校验）
- 学生信息的编辑与更新（部分字段更新）
- 学生信息的逻辑删除（status 置为 -1，不物理删除）
- 学生详情查询（Redis 缓存加速）
- 学生列表分页查询（多条件组合筛选 + 关键词模糊搜索）
- 批量学生信息查询

### 1.2 所属架构位置

本服务对应 SAD 中定义的「学生服务」组件，位于业务层，通过内部 REST API 与班级服务、年级服务协作。前端请求经由 API 网关路由至本服务。

### 1.3 分层架构

| 层级 | 职责 | 技术选型 |
|------|------|----------|
| Controller | 请求接收、参数校验、响应返回 | Spring Web MVC |
| Service | 业务逻辑编排、事务管理、缓存策略 | Spring Service |
| Repository | 数据持久化操作 | MyBatis / JPA |

---

## 2. 数据模型

### 2.1 实体：Student（学生）

学生实体表，存储学生基本档案信息。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键ID |
| student_no | VARCHAR(20) | UNIQUE, NOT NULL | 学号，唯一索引 |
| name | VARCHAR(50) | NOT NULL | 学生姓名 |
| gender | TINYINT | DEFAULT 0 | 性别：0=未知 1=男 2=女 |
| phone | VARCHAR(20) | | 联系电话 |
| email | VARCHAR(100) | | 电子邮箱 |
| birth_date | DATE | | 出生日期 |
| class_id | BIGINT | | 所属班级ID，关联班级服务 |
| grade_id | BIGINT | | 所属年级ID，关联年级服务 |
| address | VARCHAR(200) | | 家庭住址 |
| status | TINYINT | DEFAULT 1 | 状态：1=在读 0=离校 -1=逻辑删除 |
| created_at | DATETIME | NOT NULL | 创建时间 |
| updated_at | DATETIME | NOT NULL | 更新时间 |

**索引设计**：

- `PRIMARY KEY (id)`
- `UNIQUE INDEX uk_student_no (student_no)`
- `INDEX idx_class_id (class_id)`
- `INDEX idx_grade_id (grade_id)`
- `INDEX idx_status (status)`
- `INDEX idx_name (name)`

### 2.2 查询对象：StudentQuery

分页组合查询参数对象。

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| keyword | VARCHAR(50) | 否 | 搜索关键词，模糊匹配姓名或学号 |
| class_id | BIGINT | 否 | 按班级筛选 |
| grade_id | BIGINT | 否 | 按年级筛选 |
| status | TINYINT | 否 | 按状态筛选 |
| page | INT | 否 | 页码，从1开始，默认1 |
| page_size | INT | 否 | 每页条数，默认20，最大100 |

### 2.3 视图对象：StudentPageResult

分页查询结果封装。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| total | INT | 总记录数 |
| page | INT | 当前页码 |
| page_size | INT | 每页条数 |
| items | List\<Student\> | 当前页学生列表 |

---

## 3. 接口定义

### 3.1 创建学生信息

```
POST /api/v1/students
```

**请求参数**（JSON Body）：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| student_no | String | 是 | 学号，长度2-20，唯一 |
| name | String | 是 | 姓名，长度1-50 |
| gender | Integer | 否 | 性别 |
| phone | String | 否 | 联系电话 |
| email | String | 否 | 电子邮箱 |
| birth_date | String | 否 | 出生日期，格式 yyyy-MM-dd |
| class_id | Long | 否 | 班级ID |
| grade_id | Long | 否 | 年级ID |
| address | String | 否 | 家庭住址 |

**响应**：201 Created，返回 Student 完整信息

**业务逻辑**：
1. 校验必填字段（student_no、name）及其格式
2. 校验学号唯一性，若已存在返回 409 Conflict
3. 设置初始 status = 1（在读）
4. 填充 created_at、updated_at 为当前时间
5. 写入 MySQL 并返回完整学生信息

### 3.2 更新学生信息

```
PUT /api/v1/students/{id}
```

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | 是 | 学生ID |

**请求参数**（JSON Body，部分更新）：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | String | 否 | 姓名 |
| phone | String | 否 | 联系电话 |
| email | String | 否 | 电子邮箱 |
| birth_date | String | 否 | 出生日期 |
| class_id | Long | 否 | 班级ID |
| grade_id | Long | 否 | 年级ID |
| address | String | 否 | 家庭住址 |

**响应**：200 OK，返回更新后的 Student 完整信息

**业务逻辑**：
1. 校验学生 ID 是否存在，不存在返回 404 Not Found
2. 只更新传入的非 null 字段，未传字段保持原值（部分更新）
3. 更新 updated_at 为当前时间
4. 写 MySQL 后清除 Redis 缓存中该学生记录

### 3.3 删除学生信息

```
DELETE /api/v1/students/{id}
```

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | 是 | 学生ID |

**响应**：204 No Content

**业务逻辑**：
1. 校验学生 ID 是否存在，不存在返回 404 Not Found
2. 校验当前 status != -1（防止重复删除）
3. 将 status 置为 -1（逻辑删除），不物理删除数据
4. 更新 updated_at 为当前时间
5. 写 MySQL 后清除 Redis 缓存中该学生记录

### 3.4 查询学生详情

```
GET /api/v1/students/{id}
```

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | Long | 是 | 学生ID |

**响应**：200 OK，返回 Student 完整信息

**业务逻辑**：
1. 优先查询 Redis 缓存，key 格式：`student:{id}`
2. 缓存命中则直接返回，不查询数据库
3. 缓存未命中则查询 MySQL
4. MySQL 查到结果后回填 Redis 缓存（设置 TTL，如 30 分钟）
5. MySQL 查不到则返回 404 Not Found

### 3.5 分页查询学生列表

```
GET /api/v1/students
```

**请求参数**（Query String）：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| keyword | String | 否 | 搜索关键词，模糊匹配姓名或学号 |
| class_id | Long | 否 | 班级ID |
| grade_id | Long | 否 | 年级ID |
| status | Integer | 否 | 状态，默认 1 |
| page | Integer | 否 | 页码，默认 1 |
| page_size | Integer | 否 | 每页条数，默认 20，最大 100 |

**响应**：200 OK，返回 StudentPageResult

**业务逻辑**：
1. 构建动态查询条件：keyword 模糊匹配 name 或 student_no；class_id、grade_id、status 精确匹配
2. 分页参数校验：page >= 1，page_size 介于 1~100
3. 执行 count 查询获取总记录数
4. 执行分页列表查询，按 updated_at DESC 排序
5. 返回分页结果

### 3.6 批量查询学生信息

```
POST /api/v1/students/batch
```

**请求参数**（JSON Body）：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| ids | List\<Long\> | 是 | 学生ID列表，最多 100 个 |

**响应**：200 OK，返回 List\<Student\>

**业务逻辑**：
1. 校验 ids 非空且数量 <= 100
2. 对每个 id 优先查 Redis 缓存
3. 未命中的 id 统一查询 MySQL（WHERE id IN (...)）
4. MySQL 查到的结果回填 Redis 缓存
5. 合并缓存和数据库结果，按请求 ids 顺序返回

---

## 4. 错误处理策略

### 4.1 异常分类

| 异常类型 | HTTP 状态码 | 场景 | 错误码示例 |
|----------|------------|------|-----------|
| 参数校验异常 | 400 Bad Request | 必填字段缺失、格式不合法、长度超限 | STU-003 |
| 资源不存在 | 404 Not Found | ID 对应的学生记录不存在 | STU-001 |
| 业务冲突 | 409 Conflict | 学号重复、状态不允许操作 | STU-002 |
| 系统异常 | 500 Internal Server Error | 数据库连接失败、缓存不可用 | STU-900 |

### 4.2 错误码定义

| 错误码 | 说明 | 触发条件 |
|--------|------|----------|
| STU-001 | 学生不存在 | 查询/更新/删除时 ID 未找到 |
| STU-002 | 学号重复 | 创建时 student_no 已存在 |
| STU-003 | 参数校验失败 | 必填字段为空、格式错误、长度超限 |
| STU-004 | 状态不允许操作 | 对已逻辑删除的记录进行操作 |
| STU-900 | 内部服务异常 | 数据库连接异常、缓存访问异常 |

### 4.3 统一错误响应格式

```json
{
  "code": "STU-001",
  "message": "学生不存在",
  "detail": "未找到 id = 10086 的学生记录（可选）"
}
```

### 4.4 处理策略

- **参数校验**：在 Controller 层通过注解或 Validator 统一校验，无效参数返回 400，附带具体校验失败字段和原因
- **业务异常**：由 Service 层抛出业务异常，全局异常处理器捕获后转为对应 HTTP 状态码
- **系统异常**：内部错误统一返回 500，不暴露 MySQL 或 Redis 的实现细节和堆栈信息
- **幂等保证**：所有写入接口支持幂等重试（逻辑删除不重复删除、创建时唯一索引防重复插入），保证最终一致性

---

## 5. 缓存策略

### 5.1 缓存键规则

| 数据类型 | 缓存 Key 格式 | TTL |
|----------|--------------|-----|
| 单个学生 | `student:{id}` | 1800 秒（30 分钟） |

### 5.2 缓存更新策略

| 操作 | 缓存行为 |
|------|----------|
| 创建学生 | 不操作缓存 |
| 查询学生（单笔） | 先查缓存，未命中则查 DB 并回填 |
| 更新学生 | 更新 DB 后删除该 Key |
| 删除学生 | 更新 DB 后删除该 Key |
| 批量查询 | 逐个查缓存，未命中查 DB 并回填 |
| 分页列表 | 不缓存，直接查 DB |

---

## 6. 依赖关系

### 6.1 内部依赖

| 依赖服务 | 依赖内容 |
|----------|----------|
| 班级服务 | 查询班级是否存在（创建/更新时校验 class_id） |
| 年级服务 | 查询年级是否存在（创建/更新时校验 grade_id） |

### 6.2 外部依赖

| 依赖组件 | 用途 |
|----------|------|
| MySQL | 主数据持久化 |
| Redis | 热点缓存 |

---

*文档结束*
