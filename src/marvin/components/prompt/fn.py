import inspect
import re
from functools import partial, wraps
from typing import (
    Any,
    Callable,
    Optional,
    TypeVar,
    Union,
    overload,
)

import pydantic
from pydantic import BaseModel
from typing_extensions import ParamSpec, Self

from marvin._mappings.types import cast_type_to_toolset
from marvin.requests import BaseMessage as Message
from marvin.requests import Prompt
from marvin.serializers import (
    create_grammar_from_vocabulary,
    create_vocabulary_from_type,
)
from marvin.settings import settings
from marvin.utilities.jinja import (
    BaseEnvironment,
    Transcript,
)

P = ParamSpec("P")
T = TypeVar("T")
U = TypeVar("U", bound=BaseModel)


class PromptFunction(Prompt[U]):
    model_config = pydantic.ConfigDict(
        extra="allow",
    )
    temperature: Optional[float] = pydantic.Field(default=None)
    model: Optional[str] = pydantic.Field(default=None)
    messages: list[Message] = pydantic.Field(default_factory=list)

    def serialize(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True, exclude_none=True)

    def model_pair(self: Self) -> tuple[Self, type[U]]:
        if (
            not self.tools
            or not self.tools[0].function
            or not self.tools[0].function.model
        ):
            raise AttributeError("No model found.")
        return self, self.tools[0].function.model

    @overload
    @classmethod
    def as_grammar(
        cls: type[Self],
        *,
        environment: Optional[BaseEnvironment] = None,
        prompt: Optional[str] = None,
        enumerate: bool = True,
        encoder: Callable[[str], list[int]] = settings.openai.chat.completions.encoder,
        max_tokens: Optional[int] = 1,
        temperature: Optional[float] = 0,
        model: Optional[str] = None,
    ) -> Callable[[Callable[P, Any]], Callable[P, Self]]:
        pass

    @overload
    @classmethod
    def as_grammar(
        cls: type[Self],
        fn: Optional[Callable[P, Any]] = None,
        *,
        environment: Optional[BaseEnvironment] = None,
        prompt: Optional[str] = None,
        enumerate: bool = True,
        encoder: Callable[[str], list[int]] = settings.openai.chat.completions.encoder,
        max_tokens: Optional[int] = 1,
        temperature: Optional[float] = 0,
        model: Optional[str] = None,
    ) -> Callable[P, Self]:
        pass

    @classmethod
    def as_grammar(
        cls: type[Self],
        fn: Optional[Callable[P, Any]] = None,
        *,
        environment: Optional[BaseEnvironment] = None,
        prompt: Optional[str] = None,
        enumerate: bool = True,
        encoder: Callable[[str], list[int]] = settings.openai.chat.completions.encoder,
        max_tokens: Optional[int] = 1,
        temperature: Optional[float] = 0,
        model: Optional[str] = None,
    ) -> Union[
        Callable[[Callable[P, Any]], Callable[P, Self]],
        Callable[P, Self],
    ]:
        def wrapper(func: Callable[P, Any], *args: P.args, **kwargs: P.kwargs) -> Self:
            # Get the signature of the function
            signature = inspect.signature(func)
            params = signature.bind(*args, **kwargs)
            params.apply_defaults()

            vocabulary = create_vocabulary_from_type(
                inspect.signature(func).return_annotation
            )

            grammar = create_grammar_from_vocabulary(
                vocabulary=vocabulary,
                encoder=encoder,
                _enumerate=enumerate,
                max_tokens=max_tokens,
            )

            messages = Transcript(
                content=prompt or func.__doc__ or ""
            ).render_to_messages(
                **kwargs | params.arguments,
                _arguments=params.arguments,
                _options=vocabulary,
                _doc=func.__doc__,
                _source_code=(
                    "\ndef" + "def".join(re.split("def", inspect.getsource(func))[1:])
                ),
            )

            return cls(
                messages=messages,
                temperature=temperature,
                model=model,
                **grammar.model_dump(exclude_unset=True, exclude_none=True),
            )

        if fn is not None:
            return wraps(fn)(partial(wrapper, fn))

        def decorator(fn: Callable[P, Any]) -> Callable[P, Self]:
            return wraps(fn)(partial(wrapper, fn))

        return decorator

    @overload
    @classmethod
    def as_tool_call(
        cls: type[Self],
        *,
        environment: Optional[BaseEnvironment] = None,
        prompt: Optional[str] = None,
        model_name: str = "FormatResponse",
        model_description: str = "Formats the response.",
        field_name: str = "data",
        field_description: str = "The data to format.",
    ) -> Callable[[Callable[P, Any]], Callable[P, Self]]:
        pass

    @overload
    @classmethod
    def as_tool_call(
        cls: type[Self],
        fn: Optional[Callable[P, Any]] = None,
        *,
        environment: Optional[BaseEnvironment] = None,
        prompt: Optional[str] = None,
        model_name: str = "FormatResponse",
        model_description: str = "Formats the response.",
        field_name: str = "data",
        field_description: str = "The data to format.",
    ) -> Callable[P, Self]:
        pass

    @classmethod
    def as_tool_call(
        cls: type[Self],
        fn: Optional[Callable[P, Any]] = None,
        *,
        environment: Optional[BaseEnvironment] = None,
        prompt: Optional[str] = None,
        model_name: str = "FormatResponse",
        model_description: str = "Formats the response.",
        field_name: str = "data",
        field_description: str = "The data to format.",
        **kwargs: Any,
    ) -> Union[
        Callable[[Callable[P, Any]], Callable[P, Self]],
        Callable[P, Self],
    ]:
        def wrapper(func: Callable[P, Any], *args: P.args, **kwargs_: P.kwargs) -> Self:
            signature = inspect.signature(func)
            params = signature.bind(*args, **kwargs_)
            params.apply_defaults()

            toolset = cast_type_to_toolset(
                _type=inspect.signature(func).return_annotation,
                model_name=model_name,
                model_description=model_description,
                field_name=field_name,
                field_description=field_description,
            )

            messages = Transcript(
                content=prompt or func.__doc__ or ""
            ).render_to_messages(
                **kwargs_ | params.arguments,
                _doc=func.__doc__,
                _arguments=params.arguments,
                _response_model=toolset.tools[0],  # type: ignore
                _source_code=(
                    "\ndef" + "def".join(re.split("def", inspect.getsource(func))[1:])
                ),
            )

            return cls(
                messages=messages,
                tool_choice=toolset.tool_choice,
                tools=toolset.tools,
                **kwargs,
            )

        if fn is not None:
            return wraps(fn)(partial(wrapper, fn))

        def decorator(fn: Callable[P, Any]) -> Callable[P, Self]:
            return wraps(fn)(partial(wrapper, fn))

        return decorator


def prompt_fn(
    fn: Optional[Callable[P, T]] = None,
    *,
    environment: Optional[BaseEnvironment] = None,
    prompt: Optional[str] = None,
    model_name: str = "FormatResponse",
    model_description: str = "Formats the response.",
    field_name: str = "data",
    field_description: str = "The data to format.",
    **kwargs: Any,
) -> Union[
    Callable[[Callable[P, T]], Callable[P, dict[str, Any]]],
    Callable[P, dict[str, Any]],
]:
    def wrapper(
        func: Callable[P, Any], *args: P.args, **kwargs: P.kwargs
    ) -> dict[str, Any]:
        return (
            PromptFunction[BaseModel]
            .as_tool_call(
                fn=func,
                environment=environment,
                prompt=prompt,
                model_name=model_name,
                model_description=model_description,
                field_name=field_name,
                field_description=field_description,
                **kwargs,
            )(*args, **kwargs)
            .serialize()
        )

    if fn is not None:
        return wraps(fn)(partial(wrapper, fn))

    def decorator(fn: Callable[P, Any]) -> Callable[P, dict[str, Any]]:
        return wraps(fn)(partial(wrapper, fn))

    return decorator
