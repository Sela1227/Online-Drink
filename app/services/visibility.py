# -*- coding: utf-8 -*-
"""團單與投票的可見性 — 單一來源（V2.11.1 P0-05）。

為什麼要有這個檔案：原本可見性是在各路由手寫 Python 迴圈過濾，於是
`/home` 有過濾、`/home/groups`（htmx 刷新片段）沒有，私密團就從那裡漏出去；
`order_wall`、投票的三支路由也各自漏掉。散在各處的實作無法一次檢查，
所以改成 SQL 層級的共用條件 + 單一 ensure 函式。

順帶解掉迴圈內逐筆查部門的 N+1。

規則：公開 → 所有人可見；團主本人可見；管理員可見；部門限定團則需部門交集。
"""
from fastapi import HTTPException
from sqlalchemy import or_, select, true

from app.models.department import GroupDepartment, UserDepartment
from app.models.group import Group
from app.models.vote import Vote, VoteDepartment


def _my_department_ids(user):
    return select(UserDepartment.department_id).where(UserDepartment.user_id == user.id)


def visible_group_clause(user):
    """可直接放進 `.filter()` 的可見性條件。"""
    if user.is_admin:
        return true()
    dept_groups = select(GroupDepartment.group_id).where(
        GroupDepartment.department_id.in_(_my_department_ids(user))
    )
    return or_(
        Group.is_public == True,
        Group.owner_id == user.id,
        Group.id.in_(dept_groups),
    )


def ensure_group_visible(group, user, db):
    """單一團單的可見性檢查，看不到就 403。"""
    if not group.is_visible_to(user, db):
        raise HTTPException(status_code=403, detail="您無權查看此團單")


def visible_vote_clause(user):
    if user.is_admin:
        return true()
    dept_votes = select(VoteDepartment.vote_id).where(
        VoteDepartment.department_id.in_(_my_department_ids(user))
    )
    return or_(
        Vote.is_public == True,
        Vote.creator_id == user.id,
        Vote.id.in_(dept_votes),
    )


def ensure_vote_visible(vote, user, db):
    """投票的可見性檢查。部門投票原本任何人都讀得到也投得下去。"""
    if user.is_admin or vote.is_public or vote.creator_id == user.id:
        return
    vote_dept_ids = {
        vd.department_id
        for vd in db.query(VoteDepartment).filter(VoteDepartment.vote_id == vote.id).all()
    }
    # V2.11.2 N-10：原本「沒有部門就放行」，與同檔案的 visible_vote_clause（隱藏）
    # 和 Group.is_visible_to（隱藏）不一致 —— 於是私密但沒選部門的投票在列表看不到、
    # 直接連結卻進得去。這個檔案既然標榜單一來源，兩個函式的規則就不能分岔。
    user_dept_ids = {
        ud.department_id
        for ud in db.query(UserDepartment).filter(UserDepartment.user_id == user.id).all()
    }
    if not (vote_dept_ids & user_dept_ids):
        raise HTTPException(status_code=403, detail="您無權查看此投票")
