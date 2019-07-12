#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
from geometry_msgs.msg import Twist
import message_filters
from sensor_msgs.msg import Image,CameraInfo
from cv_bridge import CvBridge, CvBridgeError
from costmap_converter.msg import ObstacleArrayMsg, ObstacleMsg
from visualization_msgs.msg import Marker, MarkerArray
from geometry_msgs.msg import Point32
import numpy as np
from darknet_ros_msgs.msg import BoundingBoxes,BoundingBox
from rtabmap_ros.srv import ResetPose
import tf
import cv2
import math


class Publishsers():
    def __init__(self):
        # Publisherを作成
        self.publisher = rospy.Publisher('/move_base/TebLocalPlannerROS/obstacles', ObstacleArrayMsg, queue_size=1)
        self.marker_publisher = rospy.Publisher("/visualized_obstacle", MarkerArray, queue_size = 1)
        self.obstacle_list = ["person","obstacle"]
        self.tf_br = tf.TransformBroadcaster()
        self.tf_listener = tf.TransformListener()
        self.obstacle_msg = ObstacleArrayMsg() 
        self.marker_data = MarkerArray()
        self.now = rospy.get_rostime()
        self.prev = rospy.get_rostime()

    def make_msg(self, Depth1Image, detection_data, camera1_param):
        bboxes_from_camera1 = BoundingBoxes()
        bboxes_from_camera2 = BoundingBoxes()
        bboxes_from_camera1.header = Depth1Image.header
        #bboxes_from_camera2.header = Depth2Image.header
        self.now = rospy.get_rostime()
        self.timebefore = detection_data.header.stamp
        # Add point obstacle
        self.obstacle_msg.header.stamp = detection_data.header.stamp
        self.obstacle_msg.header.frame_id = "odom" # CHANGE HERE: odom/map
        #opencvに変換
        bridge = CvBridge()
        try:
            Depth1image = bridge.imgmsg_to_cv2(Depth1Image, desired_encoding="passthrough")
            #Depth2image = bridge.imgmsg_to_cv2(Depth2Image, desired_encoding="passthrough")
        except CvBridgeError as e:
            print(e)
        for bbox in detection_data.bounding_boxes:
            if (bbox.ymin + bbox.ymax)/2 < Depth1image.shape[0]:
                if bbox.ymax > Depth1image.shape[0]:
                    bbox.ymax = Depth1image.shape[0]
                bboxes_from_camera1.bounding_boxes.append(bbox)
            else:
                bbox.ymin = bbox.ymin - Depth1image.shape[0]
                bbox.ymax = bbox.ymax - Depth1image.shape[0]
                if bbox.ymin < 0:
                    bbox.ymin = 0
                bboxes_from_camera2.bounding_boxes.append(bbox)
        camera1_obstacle_msg, camera2_obstacle_msg = ObstacleArrayMsg(), ObstacleArrayMsg()
        camera1_marker_data, camera2_marker_data = MarkerArray(), MarkerArray()
        obstacle_msg, marker_data = self.bbox_to_position_in_odom(bboxes_from_camera1, Depth1image, camera1_param)
        #obstacle_msg, marker_data = self.bbox_to_position_in_odom(bboxes_from_camera2, Depth2image, camera2_param, len(camera1_obstacle_msg.obstacles), camera1_obstacle_msg, camera1_marker_data)
        self.obstacle_msg.obstacles, self.marker_data.markers = self.update_obstacles(self.obstacle_msg, obstacle_msg, self.marker_data, marker_data)
        
    def send_msg(self):
        self.publisher.publish(self.obstacle_msg)
        self.marker_publisher.publish(self.marker_data)      
    
    def bbox_to_position_in_odom(self, bboxes, DepthImage, camera_param, i=0, obstacle_msg=ObstacleArrayMsg(), marker_data=MarkerArray()):
        if i == 0:
            del obstacle_msg.obstacles[:]
            del marker_data.markers[:]
        for bbox in bboxes.bounding_boxes:
            if bbox.Class in self.obstacle_list:
                try:
                    tan_angle_x = camera_param[0][0]*(bbox.xmin+bbox.xmax)/2+camera_param[0][1]*(bbox.ymin+bbox.ymax)/2+camera_param[0][2]*1 
                    angle_x = math.atan(tan_angle_x)
                    if abs(math.degrees(angle_x)) < 40:
                        detected_area = DepthImage[bbox.ymin:bbox.ymax,  bbox.xmin:bbox.xmax]
                        distance_x = np.median(detected_area)/1000
                        #distance_x = distance_x + 0.15
                        distance_x = distance_x - 0.9
                        distance_y = - distance_x * tan_angle_x
                        if 1.0 < distance_x < 4.0:
                            obstacle_msg.obstacles.append(ObstacleMsg())
                            marker_data.markers.append(Marker())
                            self.tf_br.sendTransform((-distance_y, 0, distance_x), tf.transformations.quaternion_from_euler(0, 0, 0), rospy.Time.now(), bbox.Class + str(i), bboxes.header.frame_id)
                            self.tf_listener.waitForTransform("/odom", "/" + bbox.Class + str(i), rospy.Time(0), rospy.Duration(0.5))
                            obstable_position = self.tf_listener.lookupTransform("/odom", bbox.Class + str(i),  rospy.Time(0))
                            obstacle_msg.obstacles[i].header.stamp, obstacle_msg.obstacles[i].header.frame_id = bboxes.header.stamp, "odom"    
                            obstacle_msg.obstacles[i].id = i
                            obstacle_msg.obstacles[i].polygon.points = [Point32()]
                            obstacle_msg.obstacles[i].polygon.points[0].x = obstable_position[0][0]
                            obstacle_msg.obstacles[i].polygon.points[0].y = obstable_position[0][1]
                            obstacle_msg.obstacles[i].polygon.points[0].z = obstable_position[0][2]
                            marker_data.markers[i].header.stamp, marker_data.markers[i].header.frame_id = bboxes.header.stamp, "odom"     
                            marker_data.markers[i].ns, marker_data.markers[i].id = bbox.Class, i
                            marker_data.markers[i].action = Marker.ADD
                            marker_data.markers[i].pose.position.x, marker_data.markers[i].pose.position.y, marker_data.markers[i].pose.position.z = obstable_position[0][0], obstable_position[0][1], obstable_position[0][2] -0.15
                            marker_data.markers[i].pose.orientation.x, marker_data.markers[i].pose.orientation.y, marker_data.markers[i].pose.orientation.z, marker_data.markers[i].pose.orientation.w= tf.transformations.quaternion_from_euler(0, 0, 0)
                            marker_data.markers[i].color.r, marker_data.markers[i].color.g, marker_data.markers[i].color.b, marker_data.markers[i].color.a = 1, 0, 0, 1
                            marker_data.markers[i].scale.x, marker_data.markers[i].scale.y, marker_data.markers[i].scale.z = 0.2, 0.2, 1
                            marker_data.markers[i].type = 3
                            i = i + 1
                except Exception as e:
                    print(e)
        return obstacle_msg, marker_data

    def update_obstacles(self, prev_obstacle_msg, detected_obstacle_msg, prev_marker_msg, marker_msg):
        self.tf_listener.waitForTransform("/odom", "/base_link", rospy.Time(0), rospy.Duration(0.3))
        current_position = self.tf_listener.lookupTransform("/odom", "/base_link",  rospy.Time(0))
        updated_obstacle_msg = ObstacleArrayMsg() 
        updated_marker_data = MarkerArray()
        print(len(detected_obstacle_msg.obstacles))
        for detected_obstacle, marker in zip(detected_obstacle_msg.obstacles, marker_msg.markers): 
            """
            for prev_obstacle, prev_marker in zip(prev_obstacle_msg.obstacles, prev_marker_msg.markers):        
                if abs(current_position[0][0] - prev_obstacle.polygon.points[0].x) < 4 or abs(current_position[0][1] - prev_obstacle.polygon.points[0].y) < 4:
                    if ((detected_obstacle.polygon.points[0].x - prev_obstacle.polygon.points[0].x) * (detected_obstacle.polygon.points[0].x - prev_obstacle.polygon.points[0].x) + (detected_obstacle.polygon.points[0].y - prev_obstacle.polygon.points[0].y) * (detected_obstacle.polygon.points[0].y - prev_obstacle.polygon.points[0].y)) < 1.0:
                        prev_obstacle.polygon.points[0].x = detected_obstacle.polygon.points[0].x 
                        prev_obstacle.polygon.points[0].y = detected_obstacle.polygon.points[0].y
                        prev_marker.pose.position.x = marker.pose.position.x 
                        prev_marker.pose.position.y = marker.pose.position.y
                        updated_obstacle_msg.obstacles.append(detected_obstacle)                    
                        updated_marker_data.markers.append(marker)
            """
            updated_obstacle_msg.obstacles.append(detected_obstacle)                    
            updated_marker_data.markers.append(marker)
        return updated_obstacle_msg.obstacles, updated_marker_data.markers

class Subscribe_publishers():
    def __init__(self, pub):
        self.depth_subscriber = message_filters.Subscriber('/camera/aligned_depth_to_color/image_raw', Image)
        self.detection_subscriber =message_filters.Subscriber("/darknet_ros/bounding_boxes", BoundingBoxes)
        self.camera_param_subscriber = rospy.Subscriber("/camera/color/camera_info", CameraInfo, self.camera_parameter_callback)
        # messageの型を作成
        self.pub = pub
        self.camera1_parameter = CameraInfo()
        self.camera2_parameter = CameraInfo()
        ts = message_filters.ApproximateTimeSynchronizer([self.depth_subscriber, self.detection_subscriber], 10, 0.05)
        ts.registerCallback(self.bounding_boxes_callback)

    def camera_parameter_callback(self, data):
        camera_parameter_org = data.K
        camera_parameter_org = np.reshape(camera_parameter_org, (3, 3))
        self.camera1_parameter = np.linalg.inv(camera_parameter_org)
        print ("Camera parameter:")
        print (camera_parameter_org)
        self.camera_param_subscriber.unregister()    

    def bounding_boxes_callback(self, depth1_image, detection_data):
        self.pub.make_msg(depth1_image, detection_data, self.camera1_parameter)
        self.pub.send_msg()

def main():
    # nodeの立ち上げ
    rospy.init_node('publish_tree')

    # クラスの作成
    pub = Publishsers()
    sub = Subscribe_publishers(pub)

    rospy.spin()

if __name__ == '__main__':
    main()

