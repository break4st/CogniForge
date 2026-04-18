"""Custom exceptions for CogniForge"""


class CogniForgeError(Exception):
    """Base exception for CogniForge"""
    pass


class DocumentNotFoundError(CogniForgeError):
    """Document not found in wiki"""
    pass


class DocumentExistsError(CogniForgeError):
    """Document already exists"""
    pass


class TaskNotFoundError(CogniForgeError):
    """Task not found"""
    pass


class TaskDependencyError(CogniForgeError):
    """Task dependency not satisfied"""
    pass


class AgentError(CogniForgeError):
    """Agent execution error"""
    pass


class AgentRoleError(CogniForgeError):
    """Invalid agent role"""
    pass


class ContextLoadError(CogniForgeError):
    """Failed to load context"""
    pass


class GateCheckFailedError(CogniForgeError):
    """Quality gate check failed"""
    pass


class WorkflowError(CogniForgeError):
    """Workflow execution error"""
    pass


class GitStorageError(CogniForgeError):
    """Git storage operation error"""
    pass


class ConfigurationError(CogniForgeError):
    """Configuration error"""
    pass
