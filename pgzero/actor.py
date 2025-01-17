from __future__ import annotations
import pygame
from math import radians, sin, cos, atan2, degrees, sqrt

from . import game
from . import loaders
from . import rect
from . import spellcheck
from .rect import ZRect
from .collide import Collide

from typing import Sequence, Union
from pygame import Vector2
from ._common import _Coordinate, _CanBeRect, _CanBeObb
from typing import Union

ANCHORS = {
    'x': {
        'left': 0.0,
        'center': 0.5,
        'middle': 0.5,
        'right': 1.0,
    },
    'y': {
        'top': 0.0,
        'center': 0.5,
        'middle': 0.5,
        'bottom': 1.0,
    }
}


def calculate_anchor(value, dim, total):
    if isinstance(value, str):
        try:
            return total * ANCHORS[dim][value]
        except KeyError:
            raise ValueError(
                '%r is not a valid %s-anchor name' % (value, dim)
            )
    return float(value)


# These are methods (of the same name) on pygame.Rect
SYMBOLIC_POSITIONS = set((
    "topleft", "bottomleft", "topright", "bottomright",
    "midtop", "midleft", "midbottom", "midright",
    "center",
))

# Provides more meaningful default-arguments e.g. for display in IDEs etc.
POS_TOPLEFT = None
ANCHOR_CENTER = None

MAX_ALPHA = 255  # Based on pygame's max alpha.


def transform_anchor(ax, ay, w, h, angle, scale=1.0):
    """Transform anchor based upon a rotation of a surface of size w x h."""
    theta = -radians(angle)

    sintheta = sin(theta)
    costheta = cos(theta)

    # Dims of the transformed rect
    tw = abs(w * costheta) + abs(h * sintheta)
    th = abs(w * sintheta) + abs(h * costheta)

    # Offset of the anchor from the center
    cax = ax - w * 0.5
    cay = ay - h * 0.5

    # Rotated offset of the anchor from the center
    rax = cax * costheta - cay * sintheta
    ray = cax * sintheta + cay * costheta

    return (
        (tw * 0.5 + rax)*scale,
        (th * 0.5 + ray)*scale
    )


def _set_angle(actor, current_surface):
    if actor._angle % 360 == 0:
        # No changes required for default angle.
        return current_surface
    return pygame.transform.rotate(current_surface, actor._angle)


def _set_scale(actor, current_surface):
    if actor._scale == 1.0:
        # No changes required for default scale.
        return current_surface
    new_width = current_surface.get_width() * actor._scale
    new_height = current_surface.get_height() * actor._scale
    return pygame.transform.scale(current_surface, (new_width, new_height))


def _set_flip(actor, current_surface):
    if (not actor._flip_x) and (not actor._flip_y):
        # No changes required for default flip.
        return current_surface
    return pygame.transform.flip(current_surface, actor._flip_x, actor._flip_y)


def _set_opacity(actor, current_surface):
    alpha = int(actor.opacity * MAX_ALPHA + 0.5)  # +0.5 for rounding up.

    if alpha == MAX_ALPHA:
        # No changes required for fully opaque surfaces (corresponds to the
        # default opacity of the current_surface).
        return current_surface

    alpha_img = pygame.Surface(current_surface.get_size(), pygame.SRCALPHA)
    alpha_img.fill((255, 255, 255, alpha))
    alpha_img.blit(
        current_surface,
        (0, 0),
        special_flags=pygame.BLEND_RGBA_MULT
    )
    return alpha_img


class Actor:
    EXPECTED_INIT_KWARGS = SYMBOLIC_POSITIONS | set(("subrect",))
    DELEGATED_ATTRIBUTES = [
        a for a in dir(rect.ZRect) if not a.startswith("_")
    ]

    function_order = [_set_opacity, _set_scale, _set_flip, _set_angle]
    _anchor = _anchor_value = (0, 0)
    _scale = 1.0
    _flip_x = False
    _flip_y = False
    _angle = 0.0
    _opacity = 1.0

    def _surface_cachekey(self):
        if self.subrect is None:
            hashv = 0
        else:
            hashv = hash((self.subrect.x, self.subrect.y,
                          self.subrect.width, self.subrect.height))
        return self._image_name + '.' + str(hashv)

    def _build_transformed_surf(self):
        key = self._surface_cachekey()
        surface_cache = self._surface_cache[key][1]
        cache_len = len(surface_cache)
        if cache_len == 0:
            last = self._surface_cache[key][0]
        else:
            last = surface_cache[-1]
        for f in self.function_order[cache_len:]:
            new_surf = f(self, last)
            surface_cache.append(new_surf)
            last = new_surf
        return surface_cache[-1]

    def __init__(self, image, pos=POS_TOPLEFT, anchor=ANCHOR_CENTER, **kwargs):
        self._handle_unexpected_kwargs(kwargs)

        self._mask: pygame.mask.Mask = None
        self._drawed_surf: pygame.Surface = None
        self._surface_cache = []
        self._radius: float = None
        self.__dict__["_rect"] = rect.ZRect((0, 0), (0, 0))
        # Initialise it at (0, 0) for size (0, 0).
        # We'll move it to the right place and resize it later
        self._subrect = None
        self._image_name: str = None
        self.image = image
        self.subrect = kwargs.get('subrect', None)
        self._init_position(pos, anchor, **kwargs)

    def __getattr__(self, attr):
        if attr in self.__class__.DELEGATED_ATTRIBUTES:
            return getattr(self._rect, attr)
        else:
            return object.__getattribute__(self, attr)

    def __setattr__(self, attr, value):
        """Assign rect attributes to the underlying rect."""
        if attr in self.__class__.DELEGATED_ATTRIBUTES:
            return setattr(self._rect, attr, value)
        else:
            # Ensure data descriptors are set normally
            return object.__setattr__(self, attr, value)

    def __iter__(self):
        return iter(self._rect)

    def __repr__(self):
        return '<{} {!r} pos={!r}>'.format(
            type(self).__name__,
            self._image_name,
            self.pos
        )

    def __dir__(self):
        standard_attributes = [
            key
            for key in self.__dict__.keys()
            if not key.startswith("_")
        ]
        return standard_attributes + self.__class__.DELEGATED_ATTRIBUTES

    def _handle_unexpected_kwargs(self, kwargs):
        unexpected_kwargs = set(kwargs.keys()) - self.EXPECTED_INIT_KWARGS
        if not unexpected_kwargs:
            return

        typos, _ = spellcheck.compare(
            unexpected_kwargs, self.EXPECTED_INIT_KWARGS)
        for found, suggested in typos:
            raise TypeError(
                "Unexpected keyword argument '{}' (did you mean '{}'?)".format(
                    found, suggested))

    def _init_position(self, pos, anchor, **kwargs):
        if anchor is None:
            anchor = ("center", "center")
        self.anchor = anchor

        symbolic_pos_args = {
            k: kwargs[k] for k in kwargs if k in SYMBOLIC_POSITIONS}

        if not pos and not symbolic_pos_args:
            # No positional information given, use sensible top-left default
            self.topleft = (0, 0)
        elif pos and symbolic_pos_args:
            raise TypeError(
                "'pos' argument cannot be mixed with 'topleft', "
                "'topright' etc. argument."
            )
        elif pos:
            self.pos = pos
        else:
            self._set_symbolic_pos(symbolic_pos_args)

    def _set_symbolic_pos(self, symbolic_pos_dict):
        if len(symbolic_pos_dict) == 0:
            raise TypeError(
                "No position-setting keyword arguments ('topleft', "
                "'topright' etc) found."
            )
        if len(symbolic_pos_dict) > 1:
            raise TypeError(
                "Only one 'topleft', 'topright' etc. argument is allowed."
            )

        setter_name, position = symbolic_pos_dict.popitem()
        setattr(self, setter_name, position)

    def _update_transform(self, function):
        if function in self.function_order:
            i = self.function_order.index(function)
            for k in self._surface_cache.keys():
                del self._surface_cache[k][1][i:]
        else:
            raise IndexError(
                "function {!r} does not have a registered order."
                "".format(function))

    @property
    def anchor(self):
        return self._anchor_value

    @anchor.setter
    def anchor(self, val):
        self._anchor_value = val
        self._calc_anchor()

    def _calc_anchor(self):
        ax, ay = self._anchor_value
        ow, oh = self._orig_surf.get_size()
        ax = calculate_anchor(ax, 'x', ow)
        ay = calculate_anchor(ay, 'y', oh)
        self._untransformed_anchor = ax, ay
        if self._angle == 0.0:
            anchor = self._untransformed_anchor
            self._anchor = (anchor[0] * self._scale, anchor[1] * self._scale)
        else:
            self._anchor = transform_anchor(ax, ay, ow, oh, self._angle, self._scale)

    def _transform(self):
        w, h = self._orig_surf.get_size()

        ra = radians(self._angle)
        sin_a = sin(ra)
        cos_a = cos(ra)
        self.height = (abs(w * sin_a) + abs(h * cos_a))*self._scale
        self.width = (abs(w * cos_a) + abs(h * sin_a))*self._scale
        ax, ay = self._untransformed_anchor
        p = self.pos
        self._anchor = transform_anchor(ax, ay, w, h, self._angle, self._scale)
        self.pos = p

    @property
    def angle(self):
        return self._angle

    @angle.setter
    def angle(self, angle):
        if self._angle != angle:
            self._angle = angle
            self._transform()
            self._update_transform(_set_angle)

    @property
    def scale(self):
        return self._scale

    @scale.setter
    def scale(self, scale):
        if self._scale != scale:
            self._scale = scale
            self._transform()
            self._update_transform(_set_scale)

    @property
    def flip_x(self):
        return self._flip_x

    @flip_x.setter
    def flip_x(self, flip_x):
        if self._flip_x != flip_x:
            self._flip_x = flip_x
            self._update_transform(_set_flip)

    @property
    def flip_y(self):
        return self._flip_y

    @flip_y.setter
    def flip_y(self, flip_y):
        if self._flip_y != flip_y:
            self._flip_y = flip_y
            self._update_transform(_set_flip)

    @property
    def opacity(self):
        """Get/set the current opacity value.

        The allowable range for opacity is any number between and including
        0.0 and 1.0. Values outside of this will be clamped to the range.

        * 0.0 makes the image completely transparent (i.e. invisible).
        * 1.0 makes the image completely opaque (i.e. fully viewable).

        Values between 0.0 and 1.0 will give varying levels of transparency.
        """
        return self._opacity

    @opacity.setter
    def opacity(self, opacity):
        # Clamp the opacity to the allowable range.
        new_opacity = min(1.0, max(0.0, opacity))
        if self._opacity != new_opacity:
            self._opacity = new_opacity
            self._update_transform(_set_opacity)

    @property
    def pos(self):
        px, py = self.topleft
        ax, ay = self._anchor
        return px + ax, py + ay

    @pos.setter
    def pos(self, pos):
        px, py = pos
        ax, ay = self._anchor
        self.topleft = px - ax, py - ay

    def rect(self):
        """Get a copy of the actor's rect object.

        This allows Actors to duck-type like rects in Pygame rect operations,
        and is not expected to be used in user code.
        """
        return self._rect.copy()

    @property
    def x(self):
        ax = self._anchor[0]
        return self.left + ax

    @x.setter
    def x(self, px):
        self.left = px - self._anchor[0]

    @property
    def y(self):
        ay = self._anchor[1]
        return self.top + ay

    @y.setter
    def y(self, py):
        self.top = py - self._anchor[1]

    @property
    def image(self):
        return self._image_name

    @image.setter
    def image(self, image):
        if self._image_name != image:
            self._image_name = image
            self._orig_surf = loaders.images.load(image)
            key = self._surface_cachekey()
            if key not in self._surface_cache.keys():
                self._surface_cache[key] = [None] * 2
                self._surface_cache[key][0] = self._orig_surf
                self._surface_cache[key][1] = []  # Clear out old image's cache.
            self._update_pos()

    @property
    def subrect(self):
        return self._subrect

    @subrect.setter
    def subrect(self, subrect: _CanBeRect):
        subr = subrect
        if subrect is not None:
            if not isinstance(self.subrect, ZRect):
                subr = pygame.Rect(subrect)
        if subr != self._subrect:
            self._subrect = subr
            subrect_tuple = None
            if self._subrect is not None:
                subrect_tuple = (subr.x, subr.y, subr.w, subr.h)
            self._orig_surf = loaders.images.load(self.image, subrect=subrect_tuple)
            key = self._surface_cachekey()
            if key not in self._surface_cache.keys():
                self._surface_cache[key] = [None] * 2
                self._surface_cache[key][0] = self._orig_surf
                self._surface_cache[key][1] = []  # Clear out old image's cache.
            self._update_pos()

    def _update_pos(self):
        p = self.pos
        if self.subrect is None:
            self.width, self.height = self._orig_surf.get_size()
        else:
            self.width, self.height = self.subrect.width, self.subrect.height
        self._calc_anchor()
        self.pos = p

    def draw(self):
        s = self._build_transformed_surf()
        if s != self._drawed_surf:
            self._drawed_surf = s
            self._mask = None
        game.screen.blit(s, self.topleft)

    def angle_to(self, target):
        """Return the angle from this actors position to target, in degrees."""
        if isinstance(target, Actor):
            tx, ty = target.pos
        else:
            tx, ty = target
        myx, myy = self.pos
        dx = tx - myx
        dy = myy - ty   # y axis is inverted from mathematical y in Pygame
        return degrees(atan2(dy, dx))

    def distance_to(self, target):
        """Return the distance from this actor's pos to target, in pixels."""
        if isinstance(target, Actor):
            tx, ty = target.pos
        else:
            tx, ty = target
        myx, myy = self.pos
        dx = tx - myx
        dy = ty - myy
        return sqrt(dx * dx + dy * dy)

    def move_towards(self, direction: Union[int, float, Actor, _Coordinate],
                     distance, stop_on_target=True):
        """move actor position of a certain distance in pixels in a certain direction.
           this direction can be an angle in degrees or an Actor or a coordinate"""
        if isinstance(direction, (int, float)):
            angle = radians(direction)
        else:
            angle = radians(self.angle_to(direction))
            if stop_on_target:
                target_distance = self.distance_to(direction)
                if (target_distance < distance) and distance > 0:
                    distance = target_distance
        dx = distance * cos(angle)
        dy = -distance * sin(angle)
        self.pos = (self.x + dx, self.y + dy)

    def unload_image(self):
        loaders.images.unload(self._image_name)

    def mask_collidepoint(self, pt: _Coordinate):
        x, y = pt
        if self._mask is None:
            self._mask = pygame.mask.from_surface(self._build_transformed_surf())

        xoffset = int(x - self.left)
        yoffset = int(y - self.top)
        if xoffset < 0 or yoffset < 0:
            return 0

        width, height = self._mask.get_size()
        if xoffset > width or yoffset > height:
            return 0

        return self._mask.get_at((xoffset, yoffset))

    def mask_collide(self, actor):
        for a in [self, actor]:
            if a._mask is None:
                a._mask = pygame.mask.from_surface(a._build_transformed_surf())

        xoffset = int(actor.left - self.left)
        yoffset = int(actor.top - self.top)

        return self._mask.overlap(actor._mask, (xoffset, yoffset))

    def mask_collidelist(self, actors):
        for i in range(len(actors)):
            if self.mask_collide(actors[i]):
                return i
        return -1

    def mask_collidelistall(self, actors):
        collided = []
        for i in range(len(actors)):
            if self.mask_collide(actors[i]):
                collided.append(i)
        return collided

    @property
    def radius(self) -> float:
        if self._radius is not None:
            return self._radius
        else:
            return max(self._orig_surf.get_size()) * .5 * self._scale

    @radius.setter
    def radius(self, radius: float):
        self._radius = radius

    def circle_collidepoints(self, points: Sequence[_Coordinate],
                             radius: float = None) -> int:
        r = self._radius if radius is None else radius
        return Collide.circle_points(self.centerx, self.centery, r, points)

    def circle_collidepoint(self, pt: _Coordinate, radius: float = None) -> bool:
        r = self.radius if radius is None else radius
        return Collide.circle_point(self.centerx, self.centery, r, pt[0], pt[1])

    def circle_collidecircle(self, target: Union[Actor, _Coordinate],
                             radius: float = None, target_radius: float = None) -> bool:
        if isinstance(target, Actor):
            x, y = (target.centerx, target.centery)
            r2 = target.radius if target_radius is None else target_radius
        else:
            x, y = target
            r2 = target_radius

        r = self.radius if radius is None else radius

        return Collide.circle_circle(self.centerx, self.centery, r,
                                     x, y, r2)

    def circle_colliderect(self, target: Union[Actor, _CanBeRect],
                           radius: float = None) -> bool:
        rect = ZRect(target)
        r = self.radius if radius is None else radius
        return Collide.circle_rect(self.centerx, self.centery, r,
                                   rect.centerx, rect.centery, rect.width, rect.height)

    def _obb(self):
        w, h = Vector2(self._orig_surf.get_size()) * self._scale
        cx, cy = self.centerx, self.centery
        return cx, cy, w, h, self.angle

    def circle_collideobb(self, target: Actor, radius: float = None) -> bool:
        cx, cy, w, h, angle = target._obb()
        r = self.radius if radius is None else radius
        return Collide.obb_circle(cx, cy, w, h, angle,
                                  self.centerx, self.centery, r)

    def obb_collidepoint(self, pt: _Coordinate) -> bool:
        return Collide.obb_point(*self._obb(), pt[0], pt[1])

    def obb_collidepoints(self, points) -> int:
        return Collide.obb_points(*self._obb(), points)

    def obb_colliderect(self, target: Union[Actor, _CanBeRect]):
        rect = ZRect(target)
        return Collide.obb_rect(*self._obb(), rect.centerx, rect.centery,
                                rect.width, rect.height)

    def obb_collidecircle(self, target: Union[Actor, _Coordinate],
                          target_radius: float = None):
        if isinstance(target, Actor):
            x, y = (target.centerx, target.centery)
            r = target.radius if target_radius is None else target_radius
        else:
            x, y = target
            r = target_radius

        return Collide.obb_circle(*self._obb(), x, y, r)

    def obb_collideobb(self, target: Union[Actor, _CanBeObb]):
        if isinstance(target, Actor):
            obb2 = target._obb()
        else:
            rect2 = ZRect(target[0])
            angle2 = target[1]
            obb2 = rect.centerx, rect2.centery, rect2.width, rect2.height, angle2

        return Collide.obb_obb(*self._obb(), *obb2)
