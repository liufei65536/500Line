import sys
import numpy
from node import Sphere, Cube, SnowFigure

class Scene(object):
    # 放置物体时距相机的默认深度
    PLACE_DEPTH = 15.0
    def __init__(self):
        # 场景需要显示的节点列表
        self.node_list = list()
        # 当前选中的节点
        self.selected_node = None
    def add_node(self, node):
        """ 向场景添加新节点 """
        self.node_list.append(node)
    def render(self):
        """ 渲染场景 """
        for node in self.node_list:
            node.render()

    def pick(self, start, direction, mat):
        """
        Execute selection.

        start, direction describe a Ray.
        mat is the inverse of the current modelview matrix for the scene.
        """
        if self.selected_node is not None:
            self.selected_node.select(False)
            self.selected_node = None
        # Keep track of the closest hit.
        mindist = sys.maxsize
        closest_node = None
        for node in self.node_list:
            hit, distance = node.pick(start, direction, mat)
            if hit and distance < mindist:
                mindist, closest_node = distance, node
        # If we hit something, keep track of it.
        if closest_node is not None:
            closest_node.select()
            closest_node.depth = mindist
            closest_node.selected_loc = start + direction * mindist
            self.selected_node = closest_node

    def rotate_selected_color(self, forwards):
        """ Rotate the color of the currently selected node """
        if self.selected_node is None: return
        self.selected_node.rotate_color(forwards)

    def scale_selected(self, up):
        """ Scale the current selection """
        if self.selected_node is None: return
        self.selected_node.scale(up)

    def move_selected(self, start, direction, inv_modelview):
        """
        Move the selected node, if there is one.

        Consume:
        start, direction describes the Ray to move to
        mat is the modelview matrix for the scene
        """
        if self.selected_node is None: return
        # Find the current depth and location of the selected node
        node = self.selected_node
        depth = node.depth
        oldloc = node.selected_loc
        # The new location of the node is the same depth along the new ray
        newloc = (start + direction * depth)
        # transform the translation with the modelview matrix
        translation = newloc - oldloc
        pre_tran = numpy.array([translation[0], translation[1], translation[2], 0])
        translation = inv_modelview.dot(pre_tran)
        # translate the node and track its location
        node.translate(translation[0], translation[1], translation[2])
        node.selected_loc = newloc

    def place(self, shape, start, direction, inv_modelview):
        """
        Place a new node.

        Consume:
        shape the shape to add
        start, direction describes the Ray to move to
        inv_modelview is the inverse modelview matrix for the scene
        """
        new_node = None
        if shape == 'sphere':
            new_node = Sphere()
        elif shape == 'cube':
            new_node = Cube()
        elif shape == 'figure':
            new_node = SnowFigure()
        self.add_node(new_node)
        # place the node at the cursor in camera-space
        translation = (start + direction * self.PLACE_DEPTH)
        # convert the translation to world-space
        pre_tran = numpy.array([translation[0], translation[1], translation[2], 1])
        translation = inv_modelview.dot(pre_tran)
        new_node.translate(translation[0], translation[1], translation[2])